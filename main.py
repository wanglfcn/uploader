from optparse import OptionParser, make_option
from fabric.thread_handling import ThreadHandler
from handleIO import input_loop, output_loop
from fabric.context_managers import char_buffered
from fabric.state import env, env_options, default_channel

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


def execute_cmd(options):
    channel = default_channel()
    timeout = options.command_timeout

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
                capture=None, stream=sys.stdout, timeout=timeout, cmd=options.command),
            ThreadHandler('err', output_loop, channel, "recv_stderr",
                capture=None, stream=sys.stderr, timeout=timeout),
            ThreadHandler('in', input_loop, channel, using_pty)
        )

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

        for option in env_options:
            if hasattr(options, option.dest):
                env[option.dest] = getattr(options, option.dest)
            else:
                env[option.dest] = option.default

        env['host_string'] = '%s@%s:%d' % (options.user, options.host, options.port)

        execute_cmd(options)

    except Exception, e:
        print e

if __name__ == '__main__':
    main()
