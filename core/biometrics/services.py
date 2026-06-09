from core.biometrics.interfaces import BiometricAdapterInterface
from core.biometrics.zkteco_adapter import ZKTecoAdapter
from core.biometrics.hikvision_adapter import HikvisionAdapter


class AttendanceBiometricSyncService:

    def __init__(self):
        self.adapters = []

    def sync_all(self):
        results = []
        # Add devices here when configured
        return results

    def sync_device(self, device_id: str, hours_back: int = 24):
        return {"device_id": device_id, "status": "pending"}