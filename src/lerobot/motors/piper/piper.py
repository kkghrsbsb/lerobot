from dataclasses import dataclass

from piper_control import piper_connect, piper_init, piper_interface


def connect_can():
    """连接到 Piper 的 CAN 接口并返回已激活的 CAN 端口名称列表。

    Returns:
        list[str]: 激活后的 CAN 端口列表（例如 ["can0"]）

    Raises:
        ValueError: 如果未发现任何已激活的 CAN 端口，则抛出异常提示用户检查连接
    """
    ports = piper_connect.find_ports()
    print(f"Piper ports: {ports}")

    piper_connect.activate(ports)
    ports = piper_connect.active_ports()

    if not ports:
        raise ValueError("No ports found. Make sure the Piper is connected and turned on.")

    return ports


@dataclass
class PiperMotorsBusConfig:
    motors: dict[str, tuple[int, str]]


class PiperMotorsBus:
    def __init__(self, config: PiperMotorsBusConfig) -> None:
        self.ports = connect_can()
        self.robot = piper_interface.PiperInterface(can_port=self.ports[0])
        self.motors = config.motors
# todo: 参考 ref_only_piper.py
