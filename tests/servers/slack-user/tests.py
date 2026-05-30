import pytest
import random
import string
from tests.utils.test_tools import get_test_id, run_tool_test, run_resources_test


def random_id():
    """Generate a random ID string"""
    return "".join(random.choices(string.ascii_lowercase + string.digits, k=8))


# Shared context dictionary at module level
SHARED_CONTEXT = {
    "test_user_id": "",  # replace with the user ID of the user you want to test with
}

TOOL_TESTS = [
    {
        "name": "create_channel",
        "args_template": 'with name "testuserchannel{random_id}" is_private=False',
        "expected_keywords": ["channel_id"],
        "regex_extractors": {
            "channel_id": r"channel_id:\s*([A-Z0-9]+)",
        },
        "description": "Create a new Slack channel and return the channel id after you created it",
        "setup": lambda context: {"random_id": random_id()},
    },
    {
        "name": "send_message",
        "args_template": 'to channel with ID {channel_id} with text "Test user message {test_id}"',
        "expected_keywords": ["message_ts"],
        "regex_extractors": {
            "message_ts": r"message_ts:\s*([0-9.]+)",
        },
        "description": "Send a message to the channel as the user (should include 'Sent from 20x' footer)",
        "depends_on": ["channel_id"],
        "setup": lambda context: {"test_id": random_id()},
    },
    {
        "name": "read_messages",
        "args_template": "from channel with ID {channel_id}",
        "expected_keywords": ["messages_count"],
        "regex_extractors": {
            "messages_count": r"messages_count:\s*(\d+)",
        },
        "description": "Read messages from the channel",
        "depends_on": ["channel_id"],
    },
    {
        "name": "react_to_message",
        "args_template": 'to message in channel with ID {channel_id} with timestamp "{message_ts}" with reaction "thumbsup"',
        "expected_keywords": ["reaction_added", "message_ts"],
        "regex_extractors": {
            "reaction_added": r"reaction_added:\s*(true|yes)",
            "message_ts": r"message_ts:\s*([0-9.]+)",
        },
        "description": "Add a reaction to a message",
        "depends_on": ["channel_id", "message_ts"],
    },
    {
        "name": "delete_message",
        "args_template": 'from channel with ID {channel_id} with timestamp "{message_ts}"',
        "expected_keywords": ["deleted_message_ts"],
        "regex_extractors": {
            "deleted_message_ts": r"deleted_message_ts:\s*([0-9.]+)",
        },
        "description": "Delete a message from the channel",
        "depends_on": ["channel_id", "message_ts"],
    },
    {
        "name": "archive_channel",
        "args_template": "channel with ID {channel_id}",
        "expected_keywords": ["ok"],
        "regex_extractors": {
            "ok": r"ok:\s*(true|yes)",
        },
        "description": "Archive the created channel and return ok parameter from the response",
        "depends_on": ["channel_id"],
    },
]


@pytest.fixture(scope="module")
def context():
    return SHARED_CONTEXT


@pytest.mark.asyncio
async def test_resources(client, context):
    """Test resources for Slack user-token server and extract channel information"""
    response = await run_resources_test(client)
    return response


@pytest.mark.parametrize("test_config", TOOL_TESTS, ids=get_test_id)
@pytest.mark.asyncio
async def test_slack_user_tool(client, context, test_config):
    return await run_tool_test(client, context, test_config)
