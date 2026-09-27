"""Send status updates from the UNO Q Linux processor to the STM32 sketch."""

import socket
import sys


SOCKET_PATH = "/var/run/arduino-router.sock"
STATES = {"idle": 0, "receiving": 1, "working": 2, "success": 3, "error": 4}


class StatusBridge:
    def __init__(self):
        self.available = True
        self.warned = False
        self.message_id = 0

    def set(self, name):
        if not self.available:
            return
        try:
            import msgpack

            self.message_id += 1
            request = [0, self.message_id, "laya_status", [STATES[name]]]
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
                client.settimeout(1.0)
                client.connect(SOCKET_PATH)
                client.sendall(msgpack.packb(request))
                unpacker = msgpack.Unpacker(raw=False)
                while True:
                    chunk = client.recv(4096)
                    if not chunk:
                        raise RuntimeError("router closed the connection")
                    unpacker.feed(chunk)
                    for response in unpacker:
                        if response[0] == 1 and response[1] == self.message_id:
                            if response[2] is not None:
                                raise RuntimeError(str(response[2]))
                            return
        except Exception as exc:
            self.available = False
            if not self.warned:
                print(f"STM32 status unavailable: {exc}", file=sys.stderr)
                self.warned = True
