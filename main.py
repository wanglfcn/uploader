from optparse import OptionParser, make_option
from fabric.thread_handling import ThreadHandler
from fabric.io import input_loop, output_loop
from fabric.context_managers import char_buffered

import termios
import tty

import paramiko as ssh

import sys
import time


def get_system_username():
    import getpass
    username = None
    try:
        username = getpass.getuser()
    except KeyError:
        pass
    return username


def parse_options():

    optionlist = [
        make_option('-H', '--host',
                    default=None,
                    help="host"
                    ),

        make_option('-t', '--timeout',
                    type='int',
                    default=10,
                    metavar="N",
                    help="set connection timeout to N seconds"
                    ),

        make_option('-T', '--command-timeout',
                    dest='command_timeout',
                    type='int',
                    default=None,
                    metavar="N",
                    help="set remote command timeout to N seconds"
                    ),

        make_option('-u', '--user',
                    default=get_system_username(),
                    help="username to use when connecting to remote hosts"
                    ),

        make_option('-P', '--port',
                    default=22,
                    help="SSH connection port"
                    ),

        make_option('-p', '--password',
                    default=None,
                    help="password for use with authentication and/or sudo"
                    ),


        make_option('-D', '--disable-known-hosts',
                    action='store_true',
                    default=False,
                    help="do not load user known_hosts file"
                    ),

        make_option('-n', '--connection-attempts',
                    type='int',
                    metavar='M',
                    dest='connection_attempts',
                    default=1,
                    help="make M attempts to connect before giving up"
                    ),

        make_option('-c', '--command',
                    dest='command',
                    help='command')
    ]

    parser = OptionParser(
        option_list=optionlist
    )

    opts, args = parser.parse_args()
    return opts

def get_connection(options):
    client = ssh.SSHClient()
    tries = 3

    for trie in xrange(0, tries):
        try:
            kwargs = dict(
                hostname=options.host,
                port=int(options.port),
                username=options.user,
                password=options.password,
                timeout=options.timeout,
            )

            # Ready to connect

            client.load_system_host_keys()
            client.set_missing_host_key_policy(ssh.AutoAddPolicy())
            client.connect(**kwargs)
            chan = client.get_transport().open_session()
            chan.settimeout(0.1)
            chan.input_enabled = True
            return chan

        except Exception, e:
            print e


def isatty(stream):
    """Check if a stream is a tty.

    Not all file-like objects implement the `isatty` method.
    """
    fn = getattr(stream, 'isatty', None)
    if fn is None:
        return False
    return fn()


def char_buffereds(pipe):
    """
    Only applies on Unix-based systems; on Windows this is a no-op.
    """
    if not isatty(pipe):
        yield
    else:
        old_settings = termios.tcgetattr(pipe)
        tty.setcbreak(pipe)
        try:
            yield
        finally:
            termios.tcsetattr(pipe, termios.TCSADRAIN, old_settings)


def execute_cmd(options):
    channel = get_connection(options)
    timeout = None

    with char_buffered(sys.stdin):
        # Combine stdout and stderr to get around oddball mixing issues
        channel.set_combine_stderr(False)

        # Assume pty use, and allow overriding of this either via kwarg or env
        # var.  (invoke_shell always wants a pty no matter what.)
        using_pty = True
        # Request pty with size params (default to 80x24, obtain real
        # parameters if on POSIX platform)
        channel.get_pty(width=80, height=24)

        channel.invoke_shell()
        while not channel.recv_ready():
            time.sleep(0.01)

        workers = (
            ThreadHandler('out', output_loop, channel, "recv",
                capture=None, stream=sys.stdout, timeout=timeout),
            ThreadHandler('err', output_loop, channel, "recv_stderr",
                capture=None, stream=sys.stderr, timeout=timeout),
            ThreadHandler('in', input_loop, channel, using_pty)
        )

        channel.sendall(command + "\n")
        channel.sendall('exit\n')

        while True:
            if channel.exit_status_ready():
                break
            else:
                # Check for thread exceptions here so we can raise ASAP
                # (without chance of getting blocked by, or hidden by an
                # exception within, recv_exit_status())
                for worker in workers:
                    worker.raise_if_needed()
            try:
                time.sleep(ssh.io_sleep)
            except KeyboardInterrupt:
                channel.send('\x03')

        # Obtain exit code of remote program now that we're done.
        status = channel.recv_exit_status()

        # Wait for threads to exit so we aren't left with stale threads
        for worker in workers:
            worker.thread.join()
            worker.raise_if_needed()

        # Close channel
        channel.close()

        return status


def main():
    try:
        options = parse_options()
        execute_cmd(options)

    except Exception, e:
        print e

if __name__ == '__main__':
    main()
