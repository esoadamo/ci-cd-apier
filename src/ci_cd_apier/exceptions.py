class APIERClientError(Exception):
    """
    Raised when there is an error in the client request
    """
    pass


class APIERServerError(Exception):
    """
    Raised when there is an error in the server response
    """
    def __init__(self, message: str, request_id: str, request_age_public_key: str, parent: Exception):
        """
        Initialize the APIERServerError.

        :param message: Error message.
        :param request_id: ID of the request that caused the error.
        :param request_age_public_key: Public key associated with the request.
        :param parent: The original exception that caused this error.
        """
        super().__init__(message, parent)
        self.request_id = request_id
        self.request_age_public_key = request_age_public_key
        self.parent = parent
