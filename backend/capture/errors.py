class CaptureError(Exception):
    """Napaka zajema. stage: reachable | element | capture | blocked | invalid"""

    def __init__(self, message: str, stage: str = "capture"):
        super().__init__(message)
        self.stage = stage
