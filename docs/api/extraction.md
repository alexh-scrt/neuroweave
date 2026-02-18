# Extraction Pipeline

The LLM-powered entity and relation extraction system.

## ExtractionPipeline

::: neuroweave.extraction.pipeline.ExtractionPipeline
    options:
      members:
        - extract

## Result Types

### ExtractionResult

::: neuroweave.extraction.pipeline.ExtractionResult

### ExtractedEntity

::: neuroweave.extraction.pipeline.ExtractedEntity

### ExtractedRelation

::: neuroweave.extraction.pipeline.ExtractedRelation

## LLM Clients

### LLMClient Protocol

::: neuroweave.extraction.llm_client.LLMClient

### MockLLMClient

::: neuroweave.extraction.llm_client.MockLLMClient
    options:
      members:
        - set_response
        - extract
        - call_count
        - last_system_prompt
        - last_user_message

### AnthropicLLMClient

::: neuroweave.extraction.llm_client.AnthropicLLMClient
    options:
      members:
        - extract

## Utilities

### repair_llm_json

::: neuroweave.extraction.pipeline.repair_llm_json
