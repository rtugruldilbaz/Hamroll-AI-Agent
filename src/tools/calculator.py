import ast
import operator


OPERATORS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.Pow: operator.pow,
    ast.USub: operator.neg,
}


def calculate(expression: str) -> float:
    tree = ast.parse(expression, mode="eval")

    return _evaluate(tree.body)


def _evaluate(node):

    if isinstance(node, ast.Constant):
        if isinstance(node.value, (int, float)):
            return node.value

        raise ValueError("Only numbers are allowed.")

    if isinstance(node, ast.BinOp):
        operator_type = type(node.op)

        if operator_type not in OPERATORS:
            raise ValueError("Operator not allowed.")

        left = _evaluate(node.left)
        right = _evaluate(node.right)

        return OPERATORS[operator_type](left, right)

    if isinstance(node, ast.UnaryOp):
        operator_type = type(node.op)

        if operator_type not in OPERATORS:
            raise ValueError("Operator not allowed.")

        operand = _evaluate(node.operand)

        return OPERATORS[operator_type](operand)

    raise ValueError("Invalid mathematical expression.")