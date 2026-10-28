class OrchestratorError(Exception):
    status = 400


class NotFound(OrchestratorError):
    status = 404


class InvalidTransition(OrchestratorError):
    status = 409


class HashMismatch(OrchestratorError):
    """The approver saw a different change than the one now stored."""
    status = 409


class Expired(OrchestratorError):
    status = 410


class PolicyViolation(OrchestratorError):
    status = 422

    def __init__(self, issues):
        super().__init__("; ".join(i.message for i in issues))
        self.issues = issues


class MuseError(OrchestratorError):
    status = 503


class MuseUnavailable(MuseError):
    pass


class MuseRateLimited(MuseError):
    status = 429


class MuseRejected(MuseError):
    pass


class MuseBudgetReached(MuseError):
    pass


class DraftError(MuseError):
    pass
