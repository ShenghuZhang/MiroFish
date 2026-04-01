"""
自定义 LLM Client - 使用 LangChain 实现结构化输出

支持 DeepSeek、阿里百炼等不支持 OpenAI response_format 的 API
通过 LangChain 的 with_structured_output(method='function_calling') 实现
"""

import logging
import typing
from typing import ClassVar

from openai import AsyncOpenAI
from openai.types.chat import ChatCompletionMessageParam
from pydantic import BaseModel

from graphiti_core.llm_client.client import MULTILINGUAL_EXTRACTION_RESPONSES, LLMClient
from graphiti_core.llm_client.config import DEFAULT_MAX_TOKENS, LLMConfig, ModelSize
from graphiti_core.llm_client.errors import RateLimitError, RefusalError
from graphiti_core.prompts.models import Message

logger = logging.getLogger(__name__)

DEFAULT_MODEL = 'gpt-4o-mini'
DEFAULT_SMALL_MODEL = 'gpt-4o-mini'


class LangChainStructuredLLMClient(LLMClient):
    """
    使用 LangChain 实现结构化输出的 LLM 客户端

    支持 DeepSeek、阿里百炼等不支持 response_format 的 API
    通过 LangChainChain 的 with_structured_output(method='function_calling') 实现
    """

    # Class-level constants
    MAX_RETRIES: ClassVar[int] = 2

    def __init__(
        self,
        config: LLMConfig | None = None,
        cache: bool = False,
        client: typing.Any = None,
        max_tokens: int = DEFAULT_MAX_TOKENS,
    ):
        """
        Initialize the LangChainStructuredLLMClient with the provided configuration.

        Args:
            config (LLMConfig | None): The configuration for the LLM client.
            cache (bool): Whether to use caching for responses. Defaults to False.
            client (Any | None): An optional async client instance to use.
            max_tokens (int): Maximum tokens for response generation.
        """
        # Caching is not implemented
        if cache:
            raise NotImplementedError('Caching is not implemented for LangChainStructuredLLMClient')

        if config is None:
            config = LLMConfig()

        super().__init__(config, cache)

        if client is None:
            self.client = AsyncOpenAI(api_key=config.api_key, base_url=config.base_url)
        else:
            self.client = client

        self.max_tokens = max_tokens

    async def _generate_response(
        self,
        messages: list[Message],
        response_model: type[BaseModel] | None = None,
        max_tokens: int = DEFAULT_MAX_TOKENS,
        model_size: ModelSize = ModelSize.medium,
    ) -> dict[str, typing.Any]:
        """
        Generate a response using LangChain's with_structured_output with function_calling method.

        Args:
            messages: List of messages to send to the LLM
            response_model: Optional Pydantic model for structured output
            max_tokens: Maximum tokens to generate
            model_size: Size of model to use (small/medium)

        Returns:
            Dict containing the response
        """
        openai_messages: list[ChatCompletionMessageParam] = []
        for m in messages:
            m.content = self._clean_input(m.content)
            if m.role == 'user':
                openai_messages.append({'role': 'user', 'content': m.content})
            elif m.role == 'system':
                openai_messages.append({'role': 'system', 'content': m.content})

        try:
            if model_size == ModelSize.small:
                model = self.small_model or DEFAULT_SMALL_MODEL
            else:
                model = self.model or DEFAULT_MODEL

            logger.debug(f'Using model: {model}, model_size: {model_size}')

            # Import LangChain only when needed
            from langchain_openai import ChatOpenAI

            # Create LangChain ChatOpenAI instance
            langchain_llm = ChatOpenAI(
                model=model,
                api_key=self.config.api_key,
                base_url=self.config.base_url,
                temperature=self.temperature,
                max_tokens=max_tokens or self.max_tokens,
            )

            if response_model:
                # Use LangChain's with_structured_output with function_calling method
                # This is compatible with DeepSeek, ZhipuAI, and other OpenAI-compatible APIs
                structured_llm = langchain_llm.with_structured_output(
                    response_model,
                    method='function_calling'  # Use function_calling instead of json_schema
                )

                # Convert messages to LangChain format
                langchain_messages = []
                for msg in openai_messages:
                    langchain_messages.append((msg['role'], msg['content']))

                # Get structured response
                result = await structured_llm.ainvoke(langchain_messages)

                # Return as dict (Pydantic model model_dump)
                if isinstance(result, BaseModel):
                    return result.model_dump()
                return result
            else:
                # No structured output needed - use regular completion
                langchain_messages = []
                for msg in openai_messages:
                    langchain_messages.append((msg['role'], msg['content']))

                result = await langchain_llm.ainvoke(langchain_messages)
                return {'content': result.content}

        except Exception as e:
            logger.error(f'Error in generating LLM response: {e}')
            raise

    async def generate_response(
        self,
        messages: list[Message],
        response_model: type[BaseModel] | None = None,
        max_tokens: int | None = None,
        model_size: ModelSize = ModelSize.medium,
    ) -> dict[str, typing.Any]:
        """
        Generate a response with retry logic.

        Args:
            messages: List of messages to send to the LLM
            response_model: Optional Pydantic model for structured output
            max_tokens: Maximum tokens to generate
            model_size: Size of model to use (small/medium)

        Returns:
            Dict containing the response
        """
        if max_tokens is None:
            max_tokens = self.max_tokens

        retry_count = 0
        last_error = None

        # Add multilingual extraction instructions
        messages[0].content += MULTILINGUAL_EXTRACTION_RESPONSES

        while retry_count <= self.MAX_RETRIES:
            try:
                response = await self._generate_response(
                    messages, response_model, max_tokens, model_size
                )
                return response
            except (RateLimitError, RefusalError):
                # These errors should not trigger retries
                raise
            except Exception as e:
                last_error = e

                # Don't retry if we've hit the max retries
                if retry_count >= self.MAX_RETRIES:
                    logger.error(f'Max retries ({self.MAX_RETRIES}) exceeded. Last error: {e}')
                    raise

                retry_count += 1

                # Construct a detailed error message for the LLM
                error_context = (
                    f'The previous response attempt was invalid. '
                    f'Error type: {e.__class__.__name__}. '
                    f'Error details: {str(e)}. '
                    f'Please try again with a valid response, ensuring the output matches '
                    f'the expected format and constraints.'
                )

                error_message = Message(role='user', content=error_context)
                messages.append(error_message)
                logger.warning(
                    f'Retrying after application error (attempt {retry_count}/{self.MAX_RETRIES}): {e}'
                )

        # If we somehow get here, raise the last error
        raise last_error or Exception('Max retries exceeded with no specific error')
