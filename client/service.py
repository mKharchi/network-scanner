import win32serviceutil
import win32service
import win32event
import servicemanager

from client import start_client


class ClientService(win32serviceutil.ServiceFramework):
    _svc_name_ = "NetworkClient"
    _svc_display_name_ = "Network Client"
    _svc_description_ = "Network monitoring client service."

    def __init__(self, args):
        super().__init__(args)

        self.stop_event = win32event.CreateEvent(None, 0, 0, None)

    def SvcStop(self):
        self.ReportServiceStatus(win32service.SERVICE_STOP_PENDING)

        win32event.SetEvent(self.stop_event)

        self.ReportServiceStatus(win32service.SERVICE_STOPPED)

    def SvcDoRun(self):
        servicemanager.LogInfoMsg(
            "NetworkClient service started."
        )

        start_client()


if __name__ == "__main__":
    win32serviceutil.HandleCommandLine(ClientService)