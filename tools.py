"""Tool (function-calling) definitions for the OpenAI Realtime API.

To add a new tool:
1. Write a handler function: `def _handle_my_tool(api_wrapper, arguments): ...`
   `arguments` is the dict decoded from the model's function call arguments.
2. Add its JSON schema to TOOL_DEFINITIONS (sent to the API in `session.update`).
3. Register the handler in TOOL_HANDLERS under the same tool name.
4. If the model needs extra guidance to use the tool correctly, append a
   sentence to TOOL_INSTRUCTIONS (appended to the assistant's instructions).
"""

TOOL_DEFINITIONS = []
TOOL_HANDLERS = {}
TOOL_INSTRUCTIONS = []


END_CONVERSATION_TOOL_NAME = 'end_conversation'


def _handle_end_conversation(api_wrapper, arguments):
    """Mark the conversation to stop once the current response finishes playing
    """
    api_wrapper.request_end_conversation()


TOOL_DEFINITIONS.append(dict(
    type = 'function',
    name = END_CONVERSATION_TOOL_NAME,
    description = (
        "Ends the voice conversation. Call this only right after you have "
        "already said a short goodbye message to the user in this same "
        "response - never call it silently or before saying goodbye."
    ),
    parameters = dict(
        type = 'object',
        properties = {},
        required = [],
    ),
))
TOOL_HANDLERS[END_CONVERSATION_TOOL_NAME] = _handle_end_conversation
TOOL_INSTRUCTIONS.append(
    "If the user says goodbye, thanks you to close the conversation, or "
    "otherwise makes clear the conversation is over, first say a short, "
    "natural goodbye message out loud, and only then call the "
    f"'{END_CONVERSATION_TOOL_NAME}' function in that same turn to end the "
    "call. Never call that function without first saying goodbye in the "
    "same response."
)
