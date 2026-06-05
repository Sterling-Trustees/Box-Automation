class StatementError(Exception):
    pass

class ConfigurationError(StatementError):
    pass

class ParseError(StatementError):
    pass

class IndexLookupError(StatementError):
    pass

class BoxNavigationError(StatementError):
    pass

class UploadError(StatementError):
    pass
