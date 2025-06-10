from typing import List
from mcp.types import Tool

from peakflo.tools.peakflo_api import vendor_tools, invoice_tools, utility_tools


class PeakfloApiToolFactory:

    @staticmethod
    def get_all_tools() -> List[Tool]:
        return [*vendor_tools, *invoice_tools, *utility_tools]

    @staticmethod
    def build_tool(tool_schema: dict) -> Tool:
        """
        Builds a tool from a tool schema.
        TODO: Use this function to build tools from the tool schemas when extend to more than Peakflo API tools
        TODO: Add more granular control over input and output schemas
        """
        return Tool(
            name=tool_schema.get("name"),
            description=tool_schema.get("description"),
            inputSchema=tool_schema.get("inputSchema"),
            outputSchema=tool_schema.get("outputSchema"),
        )
