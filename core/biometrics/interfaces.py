from abc import ABC, abstractmethod
import datetime

class BiometricAdapterInterface(ABC):
    """
    This is the contract blueprint. Any biometric device adapter we build
    MUST have these two functions, or Python will throw an error.
    """
    @abstractmethod
    def authenticate(self, ip: str, port: int) -> bool:
        pass

    @abstractmethod
    def fetch_attendance_logs(self, ip: str, port: int, last_sync: datetime.datetime) -> list:
        pass