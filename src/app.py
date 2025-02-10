import asyncio
import logging
import os

from azure.ai.projects.aio import AIProjectClient
from azure.ai.projects.models import (
    Agent,
    AgentThread,
    AsyncFunctionTool,
    AsyncToolSet,
    BingGroundingTool,
    CodeInterpreterTool,
    FileSearchTool,
)
from azure.identity import DefaultAzureCredential
from dotenv import load_dotenv
from sales_data import SalesData
from stream_event_handler import StreamEventHandler
from terminal_colors import TerminalColors as tc
from utilities import Utilities
import chainlit as cl
from chainlit.config import config

logging.basicConfig(level=logging.ERROR)
logger = logging.getLogger(__name__)

load_dotenv()

TENTS_DATA_SHEET_FILE = "datasheet/contoso-tents-datasheet.pdf"
API_DEPLOYMENT_NAME = os.getenv("MODEL_DEPLOYMENT_NAME")
PROJECT_CONNECTION_STRING = os.environ["PROJECT_CONNECTION_STRING"]
BING_CONNECTION_NAME = os.getenv("BING_CONNECTION_NAME")
AGENT_PASSWORD = os.getenv("AGENT_PASSWORD")
MAX_COMPLETION_TOKENS = 4096
MAX_PROMPT_TOKENS = 10240
TEMPERATURE = 0.1
TOP_P = 0.1

toolset = AsyncToolSet()
sales_data = SalesData()
utilities = Utilities()

AGENT_READY = False
agent = Agent()
thread = AgentThread()

project_client = AIProjectClient.from_connection_string(
    credential=DefaultAzureCredential(),
    conn_str=PROJECT_CONNECTION_STRING,
)

functions = AsyncFunctionTool(
    {
        sales_data.async_fetch_sales_data_using_sqlite_query,
    }
)

INSTRUCTIONS_FILE = "instructions/instructions_function_calling.txt"
# INSTRUCTIONS_FILE = "instructions/instructions_code_interpreter.txt"
# INSTRUCTIONS_FILE = "instructions/instructions_file_search.txt"
# INSTRUCTIONS_FILE = "instructions/instructions_bing_grounding.txt"


async def add_agent_tools():
    """Add tools for the agent."""

    # Add the functions tool
    toolset.add(functions)

    # Add the code interpreter tool
    # code_interpreter = CodeInterpreterTool()
    # toolset.add(code_interpreter)

    # Add the tents data sheet to a new vector data store
    # vector_store = await utilities.create_vector_store(
    #     project_client,
    #     files=[TENTS_DATA_SHEET_FILE],
    #     vector_name_name="Contoso Product Information Vector Store",
    # )
    # file_search_tool = FileSearchTool(vector_store_ids=[vector_store.id])
    # toolset.add(file_search_tool)

    # Add the Bing grounding tool
    # bing_connection = await project_client.connections.get(connection_name=BING_CONNECTION_NAME)
    # bing_grounding = BingGroundingTool(connection_id=bing_connection.id)
    # toolset.add(bing_grounding)

@cl.password_auth_callback
async def auth_callback(username: str, password: str) -> cl.User | None:
    """Authenticate the user"""
    # Normally, you would check the username and password against a database.
    # Or use OAuth or custom provider for authentication.
    # See Chainlit documentation https://docs.chainlit.io/authentication/overview
    if (username, password) == ("sales@contoso.com", AGENT_PASSWORD):
        return cl.User(identifier="sales@contoso.com", metadata={"role": "sales", "provider": "credentials"})
    return None

async def initialize() -> tuple[Agent, AgentThread]:
    """Initialize the agent with the sales data schema and instructions."""
    global AGENT_READY
    global agent
    global thread
    if AGENT_READY:
        return
    
    await add_agent_tools()

    await sales_data.connect()
    database_schema_string = await sales_data.get_database_info()

    try:
        env = os.getenv("ENVIRONMENT", "local")
        INSTRUCTIONS_FILE_PATH = f"{'src/' if env == 'container' else ''}{INSTRUCTIONS_FILE}"
        
        with open(INSTRUCTIONS_FILE_PATH, "r", encoding="utf-8", errors="ignore") as file:
            instructions = file.read()

        # Replace the placeholder with the database schema string
        instructions = instructions.replace("{database_schema_string}", database_schema_string)

        print("Creating agent...")
        agent = await project_client.agents.create_agent(
            model=API_DEPLOYMENT_NAME,
            name="Contoso Sales AI Agent",
            instructions=instructions,
            toolset=toolset,
            temperature=TEMPERATURE,
            headers={"x-ms-enable-preview": "true"},
        )
        print(f"Created agent, ID: {agent.id}")

        print("Creating thread...")
        thread = await project_client.agents.create_thread()
        print(f"Created thread, ID: {thread.id}")

        config.ui.name = agent.name
        AGENT_READY = True

        return 

    except Exception as e:
        logger.error("An error occurred initializing the agent: %s", str(e))
        logger.error("Please ensure you've enabled an instructions file.")


async def cleanup(agent: Agent, thread: AgentThread) -> None:
    """Cleanup the resources."""
    await project_client.agents.delete_thread(thread.id)
    await project_client.agents.delete_agent(agent.id)
    await sales_data.close()


async def post_message(thread_id: str, content: str, agent: Agent, thread: AgentThread) -> None:
    """Post a message to the Azure AI Agent Service."""
    try:
        await project_client.agents.create_message(
            thread_id=thread_id,
            role="user",
            content=content,
        )

        stream = await project_client.agents.create_stream(
            thread_id=thread.id,
            assistant_id=agent.id,
            event_handler=StreamEventHandler(functions=functions, project_client=project_client, utilities=utilities),
            max_completion_tokens=MAX_COMPLETION_TOKENS,
            max_prompt_tokens=MAX_PROMPT_TOKENS,
            temperature=TEMPERATURE,
            top_p=TOP_P,
            instructions=agent.instructions,
        )

        async with stream as s:
            await s.until_done()
    except Exception as e:
        utilities.log_msg_purple(f"An error occurred posting the message: {str(e)}")
        await cl.Message(content="An error occurred posting the message.").send()

@cl.set_starters
async def set_starters() -> list[cl.Starter]:
    """Set the starters for the assistant"""
    return [
        cl.Starter(
            label="Help",
            message="help.",
            icon="./src/public/idea.svg",
        ),
        cl.Starter(
            label="Create a vivid pie chart of sales by region.",
            message="Create a vivid pie chart of sales by region.",
            icon="./src/public/learn.svg",
        ),
        cl.Starter(
            label="Staafdiagram van maandelijkse inkomsten voor wintersportproducten in 2023 met levendige kleuren.",
            message="Staafdiagram van maandelijkse inkomsten voor wintersportproducten in 2023 met levendige kleuren.",
            icon="./src/public/terminal.svg",
        ),
        cl.Starter(
            label="Download excel file for sales by category",
            message="Download excel file for sales by category",
            icon="./src/public/write.svg",
        ),
    ]

@cl.on_message
async def main(message: cl.Message) -> None:
    """
    Main function to run the agent.
    Example questions: Sales by region, top-selling products, total shipping costs by region, show as a pie chart.
    """
    completed = False
    
    await initialize()

    if agent is None:
        await cl.Message(content="An error occurred initializing the agent.").send()
        logger.error("Agent not initialized.")
        return
    
    if thread is None:
        await cl.Message(content="A thread wa not successfully created.").send()
        logger.error("Thread not successfully created.")
        return
    try:
        await post_message(agent=agent, thread_id=thread.id, content=message.content, thread=thread)
        
        completed = True
    # triggered when the user stops a chat
    except asyncio.exceptions.CancelledError:
        pass

    except Exception as e:
        await cl.Message(content=f"An error occurred: {e}").send()
        await cl.Message(content="Please try again in a moment.").send()
        logger.error("An error calling the LLM occurred: %s", str(e))
    finally:
        if not completed:
            await cleanup(agent, thread)
