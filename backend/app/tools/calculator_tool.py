import ast
import operator
from .registry import BaseTool, ToolResult, PermissionLevel

class CalculatorTool(BaseTool):
    name = "calculator"
    description = "Evaluates basic mathematical expressions safely"
    parameters = {
        "type": "object",
        "properties": {
            "expression": {"type": "string", "description": "Math expression (e.g., '2 + 2 * 3')"}
        },
        "required": ["expression"]
    }
    safety_level = "LOW"
    permission_level = PermissionLevel.NONE

    def safe_eval(self, node):
        operators = {
            ast.Add: operator.add,
            ast.Sub: operator.sub,
            ast.Mult: operator.mul,
            ast.Div: operator.truediv,
            ast.Pow: operator.pow,
            ast.BitXor: operator.xor,
            ast.USub: operator.neg
        }
        
        if isinstance(node, ast.Num):
            return node.n
        elif isinstance(node, ast.BinOp):
            return operators[type(node.op)](self.safe_eval(node.left), self.safe_eval(node.right))
        elif isinstance(node, ast.UnaryOp):
            return operators[type(node.op)](self.safe_eval(node.operand))
        elif isinstance(node, ast.Constant):
            return node.value
        else:
            raise TypeError(node)

    async def execute(self, parameters: dict) -> ToolResult:
        expr = parameters.get("expression")
        if not expr:
            return ToolResult(success=False, output="", error="Expression is required")

        try:
            tree = ast.parse(expr, mode='eval')
            result = self.safe_eval(tree.body)
            return ToolResult(success=True, output=str(result))
        except Exception as e:
            return ToolResult(success=False, output="", error=f"Invalid expression: {str(e)}")
