#!/usr/bin/python -u

import argparse
import concurrent.futures
from datetime import datetime, timedelta
import functools
import logging
import os
import pathlib
import re
import subprocess
import sys
import time

TOOLS = ['amd-host-image-builder', 'bootserver', 'dmar-report']


def output_on_err(*args, **kwargs):
    try:
        kwargs['capture_output'] = True
        kwargs['check'] = True
        result = subprocess.run(*args, **kwargs)
    except subprocess.CalledProcessError as cpe:
        err = cpe.stderr if 'encoding' in kwargs else cpe.stderr.decode(
            'utf-8')
        raise RuntimeError(
            f"Command {cpe.cmd!r} returned non-zero exit code {cpe.returncode}:"
            f"\n{err}"
        ) from cpe
    return result


def retry(count, sleep):
    def retry_decorator(func):
        @functools.wraps(func)
        def retry_wrapper(*args, **kwargs):
            last_err = None
            for attempt in range(count):
                try:
                    return func(*args, **kwargs)
                except Exception as err:
                    last_err = err
                    time.sleep(sleep)
                logging.info('%s attempt %d of %d.', func, attempt + 1, count)
            raise Exception(
                '{} failed after {} retries.'.format(func, count)
            ) from last_err
        return retry_wrapper
    return retry_decorator


class Target:
    def __init__(self, target):
        self.target = target

    @retry(count=3, sleep=1)
    def serial(self):
        logging.info('Grabbing VPD for target %s', self.target)
        cmd = ['pfexec', 'humility', '-t', self.target, 'vpd',
               '--device', 'Cosmo VPD', '--read']
        vpd = output_on_err(cmd, encoding='utf-8').stdout
        serial = re.search('BRM\w+', vpd)
        if serial is not None:
            return serial.group()
        logging.error(
            "Failed to get serial of target %s from VPD: %s", self.target, vpd)
        sys.exit(1)

    @retry(count=3, sleep=1)
    def power_off(self):
        logging.info('Powering off target %s', self.target)
        cmd = ['pfexec', 'humility', '-t', self.target, 'hiffy',
               '-c', 'Sequencer.set_state', '-a', 'state=A2']
        output_on_err(cmd)

    @retry(count=3, sleep=1)
    def power_on(self):
        logging.info('Powering on target %s', self.target)
        cmd = ['pfexec', 'humility', '-t', self.target, 'hiffy',
               '-c', 'Sequencer.set_state', '-a', 'state=A0']
        output_on_err(cmd)

    @retry(count=3, sleep=1)
    def detach_console_proxy(self):
        logging.info('Setting host console uart client to MGS on target %s',
                     self.target)
        cmd = [
            'pfexec',
            'humility',
            '-t',
            self.target,
            'console-proxy',
            'detach'
        ]
        output_on_err(cmd)

    @retry(count=3, sleep=1)
    def uart_redirect(self, enable):
        logging.info('%s UART redirection on target %s',
                     "Enabling" if enable else "Disabling", self.target)
        cmd = [
            'pfexec',
            'humility',
            '-t',
            self.target,
            'hiffy',
            '-c',
            'FmcDemo.poke32',
            '-a',
            'addr=0x60000700,value=0x{}'.format('1' if enable else '0')
        ]
        output_on_err(cmd)

    @retry(count=3, sleep=1)
    def enable_netboot(self):
        logging.info('Enabling net boot for target %s', self.target)
        cmd = ['pfexec', 'humility', '-t', self.target, 'hiffy',
               '-c', 'ControlPlaneAgent.set_startup_options', '-a',
               'startup_options=0x198']
        output_on_err(cmd)

    @retry(count=3, sleep=1)
    def last_post_code(self):
        cmd = ['pfexec', 'humility', '-t', self.target, 'hiffy',
               '-c', 'FmcDemo.peek32', '-a', 'addr=0x60000220']
        return output_on_err(cmd, encoding='utf-8').stdout.strip().split()[-1]

    @retry(count=3, sleep=1)
    def write_rom(self, image):
        logging.info('Switching to Flash1 for target %s', self.target)
        set_dev_cmd = ['pfexec', 'humility', '-t', self.target, 'hiffy',
                       '-c', 'HostFlash.set_dev', '-a', 'dev=Flash1']
        output_on_err(set_dev_cmd)
        flash_cmd = ['pfexec', 'humility', '-t', self.target, 'qspi',
                     '-D', image]
        # Don't use output_on_err because we don't want to capture output
        subprocess.run(flash_cmd, check=True)

    @retry(count=3, sleep=1)
    def console(self):
        logging.info('Attaching to console for target %s', self.target)
        cmd = ['pfexec', 'humility', '-t', self.target, 'exec', 'console']
        p = subprocess.Popen(cmd, bufsize=1, text=True, encoding='utf-8',
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                             stdin=subprocess.PIPE)
        return p


class Runner:
    def __init__(self):
        self.target = None
        self.inventron_env = None
        self.serial = None
        self.tools = {}
        self.fw_path = None
        self.phase1 = None
        self.phase2 = None
        self.power_on_time = None
        self.phbl_time = None
        self.nic = None
        self.target_ip = None
        self.target_mac = None

    def main(self, args):
        if not os.path.isdir(args.fw_path):
            logging.error("Firmware directory missing - %s", args.fw_path)
            sys.exit(1)
        self.fw_path = args.fw_path

        tools_path = pathlib.Path(args.tools_path)
        for tool in TOOLS:
            tool_path = tools_path / tool
            if not tool_path.exists():
                logging.error("%s tool not found in %s", tool, tools_path)
                sys.exit(1)
            self.tools[tool] = tool_path

        image_dir = pathlib.Path(args.IMAGE_DIR)
        phase1 = image_dir / "phbl/x86_64-oxide-none-elf/release/phbl"
        phase2 = image_dir / "zfs.img"
        if not image_dir.is_dir():
            logging.error("Image directory missing - %s", image_dir)
            sys.exit(1)
        if not phase1.is_file():
            logging.error("Phase 1 phbl payload not present in image dir")
            sys.exit(1)
        if not phase2.is_file():
            logging.error("Phase 2 zfs image not present in image dir")
            sys.exit(1)
        self.phase1 = phase1
        self.phase2 = phase2

        efs_json = pathlib.Path(args.EFS_JSON)
        if not efs_json.is_file():
            logging.error("EFS json does not exist - %s", efs_json)
            sys.exit(1)

        self.nic = args.interface
        if self.nic is None:
            cmd = 'ipadm show-addr -po ADDROBJ,TYPE | grep addrconf | head -1'
            self.nic = output_on_err(
                cmd, shell=True, text=True).stdout.split('/')[0]

        self.inventron_env = args.env or args.TARGET
        self.target = Target(args.TARGET)

        print("DRAM Margining (", args.TARGET, ")")

        self.assert_hold()

        print("Preparing target for testing...")
        self.target.power_off()
        self.target.uart_redirect(True)
        self.target.enable_netboot()
        self.serial = self.target.serial()
        logging.info("Serial: %s", self.serial)

        print("Creating boot image...")
        self.create_boot_image(efs_json)

        print("Writing image to target...")
        self.target.write_rom(self.boot_image)

        console = self.target.console()
        last_post_code = None

        print("Starting testing...")
        self.power_on_time = datetime.now()
        self.target.power_on()

        executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)
        con_task = executor.submit(Runner.monitor_console, self, console)
        last_note = time.time()
        while True:
            elapsed = datetime.now() - self.power_on_time
            if elapsed > timedelta(hours=2):
                con_task.cancel()
                try:
                    console.communicate("\x01\x18", timeout=10)
                except subprocess.TimeoutExpired:
                    pass
                console.kill()
                executor.shutdown()
                raise RuntimeError(f"Timing out after {elapsed}")

            post_code = self.target.last_post_code()
            if post_code != last_post_code:
                logging.info("POST code: %s", post_code)
                last_post_code = post_code
                if post_code == "0xea00e342":
                    print(f"PMU Training Complete ({elapsed})")
                elif post_code == "0xea00e324":
                    print(f"MBIST Interface Test ({elapsed})")
                elif post_code == "0xea00e325":
                    print(f"MBIST DataEye Test ({elapsed})")
                elif post_code == "0xee1000b0":
                    print(f"AGESA complete ({elapsed})")

            try:
                self.target_mac = con_task.result(timeout=2)
                break
            except concurrent.futures.TimeoutError:
                now_note = time.time()
                if now_note - last_note >= 15:
                    print(f"Waiting for phase 2 request... elapsed {datetime.now() - self.power_on_time}")
                    last_note = now_note
                continue

        # We don't need the console anymore, send Ctrl-A Ctrl-X to exit
        try:
            console.communicate("\r\n\r\n\x01\x18", timeout=10)
        except subprocess.TimeoutExpired:
            pass
        # If for some reason picocom failed to exit, kill it
        console.kill()
        # The host expects hardware flow control so without something on the
        # other side properly signalling, it will just get stuck.
        # To get around that, we disable the UART redirect letting the SP
        # handle it.
        self.target.uart_redirect(False)
        # We also make sure that the Host UART client is not
        # humility (which will stop reading if the SP buffer is full) but
        # rather MGS (which will discard if the SP buffer is full)
        self.target.detach_console_proxy()

        # Serve the phase2 image
        logging.info("Serving phase 2 image %s to %s", self.phase2, self.target_mac)
        self.serve_phase2()
        phase2_time = datetime.now()

        # Now wait for the target to come up and announce itself
        print("Waiting for", self.serial, "to boot...")
        pilot_cmd = ['pilot', 'host', '-i', self.nic, 'stream']
        logging.info('pilot command: %s', ' '.join(pilot_cmd))
        pilot = subprocess.Popen(pilot_cmd, bufsize=1, text=True,
                                 encoding='utf-8', stdin=subprocess.DEVNULL,
                                 stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        wait_task = executor.submit(Runner.wait_for_target, self, pilot)
        try:
            self.target_ip = wait_task.result(timeout=10*60)
            # The pilot command should not return normally and keep outputting
            # to stdout. Make sure it hasn't otherwise failed.
            if self.target_ip is None:
                cmd = " ".join(pilot_cmd)
                _, pilot_stderr = pilot.communicate(timeout=10*60)
                raise RuntimeError(
                    "Failed to discover target IP via pilot beacon - "
                    f"(cmd={pilot_cmd}, exitcode={pilot.returncode}):\n"
                    f"{pilot_stderr}"
                )
        except concurrent.futures.TimeoutError:
            wait_task.cancel()
            try:
                _, pilot_stderr = pilot.communicate(timeout=5)
                logging.error('pilot timeout; stderr: %s', pilot_stderr.strip() if pilot_stderr else '')
            except Exception:
                pass
            pilot.terminate()
            executor.shutdown()
            raise RuntimeError("Timed out waiting for pilot beacon")
        executor.shutdown()

        print("Begin DRAM Margining results collection...")
        self.copy_to_target(self.tools['dmar-report'], '/tmp/')
        results = self.run_on_target('/tmp/dmar-report').strip()
        logging.info('Results @ %s:%s', self.serial, results)
        self.copy_from_target(results, '.')

        print("DRAM Margining Test Results:", pathlib.Path(results).name)

        print("Elapsed from power on: ", datetime.now() - self.power_on_time)

        self.target.uart_redirect(True)

    def assert_hold(self):
        logging.info("Ensuring inventron hold on %s", self.inventron_env)
        cmd = ['inventron', 'env', 'assert', self.inventron_env]
        try:
            subprocess.run(cmd, capture_output=True, check=True)
        except subprocess.CalledProcessError as cpe:
            raise RuntimeError("No hold on {}".format(self.inventron_env))

    def run_on_target(self, cmd):
        if logging.getLogger().isEnabledFor(logging.INFO):
            logging.info('on-target: %s', cmd)
        ssh_cmd = [
            'ssh',
            '-oStrictHostKeyChecking=no',
            '-oUserKnownHostsFile=/dev/null',
            'root@{}%{}'.format(self.target_ip, self.nic),
            cmd,
        ]
        return output_on_err(ssh_cmd, encoding='utf-8').stdout

    def copy_from_target(self, src, dst):
        if logging.getLogger().isEnabledFor(logging.INFO):
            logging.info('from-target: %s -> %s', src, dst)
        scp_cmd = [
            'scp',
            '-oStrictHostKeyChecking=no',
            '-oUserKnownHostsFile=/dev/null',
            '-oHostname={}%%{}'.format(self.target_ip, self.nic),
            'root@dummyhost:{}'.format(src),
            dst,
        ]
        output_on_err(scp_cmd)

    def copy_to_target(self, src, dst):
        if logging.getLogger().isEnabledFor(logging.INFO):
            logging.info('to-target: %s -> %s', src, dst)
        scp_cmd = [
            'scp',
            '-oStrictHostKeyChecking=no',
            '-oUserKnownHostsFile=/dev/null',
            '-oHostname={}%%{}'.format(self.target_ip, self.nic),
            src,
            'root@dummyhost:{}'.format(dst),
        ]
        output_on_err(scp_cmd)

    def wait_for_target(self, pilot):
        for line in pilot.stdout:
            if self.serial in line:
                return line.split()[1]

    def monitor_console(self, console):
        for line in console.stdout:
            if line.startswith("Oxide Pico Host Boot Loader"):
                self.phbl_time = datetime.now()
                elapsed = self.phbl_time - self.power_on_time
                print(f"Booted to x86 ({elapsed} elapsed)")
                print("Waiting for phase 2 request...")
            elif line.startswith("NOTICE: MAC address is"):
                mac = re.search('(([0-9a-fA-F]){2}:){5}([0-9a-fA-F]){2}', line)
                if mac is None:
                    raise RuntimeError(
                        f"Failed to parse MAC from console: {line}")
                return mac.group()

    def serve_phase2(self):
        cmd = [
            'pfexec',
            self.tools['bootserver'],
            '-s',
            self.nic,
            self.phase2,
            self.target_mac,
        ]
        subprocess.run(cmd, check=True)

    def create_boot_image(self, config):
        base = pathlib.Path(config).name
        self.boot_image = base.removesuffix('.efs.json5').removesuffix(
            '.json5').removesuffix('.json') + '.rom'
        logging.info('Creating boot image %s', self.boot_image)
        cmd = [
            self.tools['amd-host-image-builder'],
            'generate',
            '-B',
            self.fw_path,
            '-c',
            config,
            '-r',
            self.phase1,
            '-o',
            self.boot_image,
        ]
        output_on_err(cmd)


if __name__ == '__main__':
    script_dir = os.path.dirname(sys.argv[0])

    parser = argparse.ArgumentParser(
        description="Creates and boots an MBIST enabled image to run on the \
                    target system and collect the results.")

    parser.add_argument('IMAGE_DIR', help="Helios Image Directory",)
    parser.add_argument('EFS_JSON', help="Boot Image EFS Config")
    parser.add_argument('TARGET', help="Humility Target")

    parser.add_argument(
        '--fw-path',
        default="{}/../amd-firmware/BRH/1.0.0.5".format(script_dir),
        help="Path to required firmware blobs")
    parser.add_argument(
        '--tools-path',
        default=script_dir,
        help="Path to required tools ({})".format(', '.join(TOOLS)))
    parser.add_argument(
        '-i', '--interface',
        help="Network interface providing connectivity to target")
    parser.add_argument(
        '-e', '--env',
        help="Inventron environment for target (if different than TARGET)"
    )

    parser.add_argument(
        '-v', '--verbose',
        action="store_true",
        help="Enable verbose logging")

    args = parser.parse_args()
    if args.verbose:
        logging.basicConfig(level=logging.INFO)

    Runner().main(args)

