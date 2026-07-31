class RichContentError(ValueError):
    """Safe validation failure for optional rich response composition."""


class UnknownBlockError(RichContentError):
    pass


class BlockVersionError(RichContentError):
    pass
