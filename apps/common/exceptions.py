class AppError(Exception):
    # `data` is an additive extension beyond the base guidelines.md contract --
    # needed for endpoints like verify-otp whose documented error body includes
    # `data.attemptsRemaining` alongside the standard {code, message} error.
    # Defaults to None, which keeps the response shape byte-identical to the
    # base contract for every call site that doesn't pass it.
    def __init__(self, message: str, status_code: int, code: str, data=None):
        self.message = message
        self.status_code = status_code
        self.code = code
        self.data = data
        super().__init__(message)


class NotFoundError(AppError):
    def __init__(self, entity: str, id: str):
        super().__init__(f"{entity} not found: {id}", 404, "NOT_FOUND")


class ForbiddenError(AppError):
    def __init__(self, message="Access denied"):
        super().__init__(message, 403, "FORBIDDEN")


class ValidationError(AppError):
    def __init__(self, message: str, code="VALIDATION_ERROR"):
        super().__init__(message, 400, code)


class ConflictError(AppError):
    def __init__(self, message: str, code="CONFLICT"):
        super().__init__(message, 409, code)
