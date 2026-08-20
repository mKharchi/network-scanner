import win32serviceutil
import win32service
import servicemanager
import threading

from client import start_client


class ClientService(win32serviceutil.ServiceFramework):
    _svc_name_ = "NetworkClient"
    _svc_display_name_ = "Network Client"
    _svc_description_ = "Network monitoring client service."

    def __init__(self, args):
        super().__init__(args)

        self.stop_event = threading.Event()

    def SvcStop(self):
        self.ReportServiceStatus(win32service.SERVICE_STOP_PENDING)

        self.stop_event.set()

    def SvcDoRun(self):
        servicemanager.LogInfoMsg(
            "NetworkClient service started."
        )

        self.ReportServiceStatus(win32service.SERVICE_RUNNING)

        try:
            start_client(self.stop_event)
        finally:
            self.ReportServiceStatus(win32service.SERVICE_STOPPED)


if __name__ == "__main__":
    win32serviceutil.HandleCommandLine(ClientService)
