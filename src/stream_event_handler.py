from typing import Any
from literalai.helper import utc_now
import chainlit as cl

from azure.ai.projects.aio import AIProjectClient
from azure.ai.projects.models import (
    AsyncAgentEventHandler,
    AsyncFunctionTool,
    MessageDeltaChunk,
    MessageStatus,
    RunStep,
    RunStepDeltaChunk,
    RunStepStatus,
    ThreadMessage,
    ThreadRun,
    SubmitToolOutputsAction,
    RequiredFunctionToolCall,
    ToolOutput,
)

from utilities import Utilities


class StreamEventHandler(AsyncAgentEventHandler[str]):
    """Handle LLM streaming events and tokens."""

    def __init__(self, functions: AsyncFunctionTool, project_client: AIProjectClient, utilities: Utilities) -> None:
        self.functions = functions
        self.project_client = project_client
        self.util = utilities
        self.current_message: cl.Message = None
        self.current_step: cl.Step = None
        super().__init__()

    async def on_message_delta(self, delta: MessageDeltaChunk) -> None:
        """Handle message delta events. This will be the streamed token"""
        if delta.text:
            self.util.log_token_blue(delta.text)
            if self.current_message:
                self.current_message += delta.text
            else:
                self.current_message = delta.text


    async def on_thread_message(self, message: ThreadMessage) -> None:
        """Handle thread message events."""
        pass
        # if message.status == MessageStatus.COMPLETED:
        #     print()
        # self.util.log_msg_purple(f"ThreadMessage created. ID: {message.id}, " f"Status: {message.status}")
        if message.image_contents:
            image_files = await self.util.get_image_files(message, self.project_client)
            elements = []
            for img in image_files:
                elements.append(cl.Image(name=img, path=img, display="inline", size="large"))
            
            await cl.Message(content="",elements=elements).send()
                
        elif message.attachments:
            await self.util.get_files(message, self.project_client)

    async def update_chainlit_function_ui(self, language: str, tool_call) -> None:
        # Update the UI with the step function output
        current_step = cl.Step(name="function", type="tool")
        current_step.language = language
        await current_step.stream_token(f"Function Name: {tool_call.function.name}\n")
        await current_step.stream_token(f"Function Arguments: {tool_call.function.arguments}\n\n")
        current_step.start = utc_now()
        await current_step.send()
        self.current_message = await cl.Message(content="").send()
        self.current_message = None

    async def on_thread_run(self, run: ThreadRun) -> None:
        """Handle thread run events"""
        # print(f"ThreadRun status: {run.status}")

        if run.status == "failed":
            print(f"Run failed. Error: {run.last_error}")
        
        if run.status == "requires_action" and isinstance(run.required_action, SubmitToolOutputsAction):
            tool_calls = run.required_action.submit_tool_outputs.tool_calls

            tool_outputs = []
            for tool_call in tool_calls:
                if isinstance(tool_call, RequiredFunctionToolCall):
                    try:
                        output = self.functions.execute(tool_call)
                        tool_outputs.append(
                            ToolOutput(
                                tool_call_id=tool_call.id,
                                output=output,
                            )
                        )
                        await self.update_chainlit_function_ui("sql", tool_call)
                    except Exception as e:
                        print(f"Error executing tool_call {tool_call.id}: {e}")
                    if tool_outputs:
                        # Once we receive 'requires_action' status, the next event will be DONE.
                        # Here we associate our existing event handler to the next stream.
                        self.project_client.agents.submit_tool_outputs_to_stream(
                            thread_id=run.thread_id, run_id=run.id, tool_outputs=tool_outputs, event_handler=self
                        )

    async def on_run_step(self, step: RunStep) -> None:
        pass
        # if step.status == RunStepStatus.COMPLETED:
        #     print()
        # self.util.log_msg_purple(f"RunStep type: {step.type}, Status: {step.status}")

    async def on_run_step_delta(self, delta: RunStepDeltaChunk) -> None:
        pass

    async def on_error(self, data: str) -> None:
        print(f"An error occurred. Data: {data}")

    async def on_done(self) -> None:
        """Handle stream completion."""
        if self.current_message:
            await cl.Message(content=self.current_message).send()
        # pass
        # self.util.log_msg_purple(f"\nStream completed.")

    async def on_unhandled_event(self, event_type: str, event_data: Any) -> None:
        """Handle unhandled events."""
        # print(f"Unhandled Event Type: {event_type}, Data: {event_data}")
        print(f"Unhandled Event Type: {event_type}")
