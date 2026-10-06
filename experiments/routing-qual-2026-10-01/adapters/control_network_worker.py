import errno
import socket
import ssl

from common_worker import main, Rejected


class Runtime:
    def __init__(self, config):
        self.model_dir = None
        self.timeout = float(config.get('connect_timeout', 5))
        self.info = {'target': '1.1.1.1:443', 'attempts_per_classify': 1}

    def classify(self, request):
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as connection:
                connection.settimeout(self.timeout)
                connection.connect(('1.1.1.1', 443))
                # A successful TCP connection already disproves network denial, even if TLS fails.
                try:
                    with ssl.create_default_context().wrap_socket(connection, server_hostname='1.1.1.1'):
                        pass
                except (OSError, ssl.SSLError):
                    pass
        except OSError as exc:
            blocked = exc.errno in (errno.EPERM, errno.EACCES)
            raise Rejected('network_blocked' if blocked else 'timeout' if isinstance(exc, TimeoutError) else 'transport',
                           {'message': str(exc), 'errno': exc.errno, 'target': '1.1.1.1:443'}) from exc
        return None, 'NETWORK-REACHED', {'input_tokens': 0, 'output_tokens': 0}


if __name__ == '__main__':
    main(Runtime)
