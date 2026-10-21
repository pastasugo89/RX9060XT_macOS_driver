#!/usr/bin/env python3
"""Create a separate, one-shot VFIO boot. No live unbind/reset or partition edits.

Run with pkexec, after review. The normal kernel/initramfs/defaults are preserved.
A FAT environment flag is cleared by GRUB BEFORE selecting the test entry; if
that write fails, the test is not selected. This avoids Btrfs grubenv writes.
"""
import argparse
import datetime
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess

ROOT_UUID = '3be4b3ea-fd40-40a5-ac88-c34b2abf0ebe'
ESP_UUID = '04BD-A73B'
ENTRY = 'rx9060xt-vfio-test'
ENV = Path('/boot/efi/EFI/cachyos/rx9060xt-vfio-test.env')
IMAGE = Path('/boot/initramfs-linux-cachyos-vfio-test.img')
CONF = Path('/etc/mkinitcpio-vfio-test.conf')
ONCE = Path('/etc/grub.d/09_rx9060xt_vfio_once')
MENU = Path('/etc/grub.d/42_rx9060xt_vfio_test')
ACCESS = Path('/usr/local/sbin/rx9060xt-vfio-access.py')
UNIT = Path('/etc/systemd/system/rx9060xt-vfio-access.service')
CFG = Path('/boot/grub/grub.cfg')
STATE = Path('/mnt/vm/backups/vfio-test-boot-state.json')


def run(*args, **kwargs):
    return subprocess.run(args, check=True, text=True, **kwargs)


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def write(path, text, mode=0o644):
    path.write_text(text)
    path.chmod(mode)


def validate_host():
    assert os.geteuid() == 0, 'Serve pkexec/root'
    assert run('findmnt', '-n', '-o', 'UUID', '--target', '/', capture_output=True).stdout.strip() == ROOT_UUID
    assert run('findmnt', '-n', '-o', 'UUID', '--target', '/boot/efi', capture_output=True).stdout.strip() == ESP_UUID
    assert run('findmnt', '-n', '-o', 'UUID', '--target', '/mnt/vm', capture_output=True).stdout.strip() == 'be2a9624-d2c1-4778-ac99-fcf9258d3328'
    for addr, device in [('0000:03:00.0', '0x7590'), ('0000:03:00.1', '0xab40'), ('0000:0a:00.0', '0x164e')]:
        p = Path('/sys/bus/pci/devices') / addr
        assert (p / 'vendor').read_text().strip() == '0x1002'
        assert (p / 'device').read_text().strip() == device
    for device in ('0x7590', '0xab40'):
        matches = [p for p in Path('/sys/bus/pci/devices').iterdir()
                   if (p / 'vendor').read_text().strip() == '0x1002' and (p / 'device').read_text().strip() == device]
        assert len(matches) == 1, 'IDs VFIO non univoci: non catturare altre schede'
    connected = [p for p in Path('/sys/class/drm').glob('card*-*') if (p / 'status').exists() and (p / 'status').read_text().strip() == 'connected']
    assert connected, 'Nessun monitor rilevato'
    for p in connected:
        card = p.name.split('-', 1)[0]
        assert (Path('/sys/class/drm') / card / 'device').resolve().name == '0000:0a:00.0', 'Monitor ancora su RX'
    assert subprocess.run(['pgrep', '-f', '^qemu-system-x86_64'], capture_output=True).returncode == 1, 'VM ancora accesa'


ACCESS_TEXT = '''#!/usr/bin/python3
import json, pathlib, subprocess, os
assert os.geteuid() == 0
assert 'rx9060xt_vfio_test=1' in pathlib.Path('/proc/cmdline').read_text().split()
subprocess.run(['udevadm', 'settle', '--timeout=30'], check=True)
devices = []
for address, device_id in [('0000:03:00.0', '0x7590'), ('0000:03:00.1', '0xab40')]:
    p = pathlib.Path('/sys/bus/pci/devices') / address
    assert (p / 'vendor').read_text().strip() == '0x1002'
    assert (p / 'device').read_text().strip() == device_id
    assert (p / 'driver').resolve().name == 'vfio-pci'
    group = (p / 'iommu_group').resolve()
    assert sorted(x.name for x in (group / 'devices').iterdir()) == [address]
    node = pathlib.Path('/dev/vfio') / group.name
    assert node.is_char_device()
    subprocess.run(['setfacl', '-m', 'u:1000:rw', str(node)], check=True)
    devices.append({'pci': address, 'group': group.name, 'driver': 'vfio-pci'})
out = pathlib.Path('/mnt/vm/builds/vfio-boot-result.json')
out.write_text(json.dumps({'boot_id': pathlib.Path('/proc/sys/kernel/random/boot_id').read_text().strip(), 'devices': devices, 'hardware_test_run': False}, indent=2))
os.chown(out, 1000, 1000)
'''


def prepare():
    assert not STATE.exists(), 'Preparazione già registrata: verificare lo stato prima di ripetere'
    for path in (ENV, IMAGE, CONF, ONCE, MENU, ACCESS, UNIT):
        assert not path.exists(), f'Non sovrascrivere {path}'
    boot_id = Path('/proc/sys/kernel/random/boot_id').read_text().strip()
    backup = Path('/mnt/vm/backups') / ('host-vfio-' + datetime.datetime.now().strftime('%Y%m%d-%H%M%S'))
    backup.mkdir()
    shutil.copy2(CFG, backup / 'grub.cfg')
    original_images = {str(p): digest(p) for p in (Path('/boot/vmlinuz-linux-cachyos'), Path('/boot/initramfs-linux-cachyos.img'), Path('/etc/default/grub'), Path('/etc/mkinitcpio.conf'))}
    old_cfg = CFG.read_text()
    match = re.search(r"^menuentry 'CachyOS Linux'.*?^}\n", old_cfg, re.M | re.S)
    assert match, 'Voce Linux normale non riconosciuta'
    normal = match.group(0)
    assert normal.count('\n\tlinux\t') == 1 and normal.count('\n\tinitrd\t') == 1
    body = normal[normal.index('\n') + 1:]
    linux = next(s for s in body.splitlines() if s.lstrip().startswith('linux\t'))
    assert '/@/boot/vmlinuz-linux-cachyos ' in linux and 'root=UUID=' + ROOT_UUID in linux
    flags = ' vfio-pci.ids=1002:7590,1002:ab40 vfio-pci.disable_vga=1 initcall_blacklist=sysfb_init kvm.ignore_msrs=1 rx9060xt_vfio_test=1'
    body = body.replace(linux, linux + flags).replace('/@/boot/initramfs-linux-cachyos.img', '/@/boot/initramfs-linux-cachyos-vfio-test.img')
    menu = f"#!/bin/sh\nexec tail -n +3 $0\nmenuentry 'CachyOS - RX9060XT VFIO test (iGPU host)' --id '{ENTRY}' {{\n" + body
    once = f'''#!/bin/sh
exec tail -n +3 $0
if search --no-floppy --fs-uuid --set=rx9060xt_esp {ESP_UUID}; then
    set rx9060xt_env="($rx9060xt_esp)/EFI/cachyos/rx9060xt-vfio-test.env"
    if [ -f "$rx9060xt_env" ]; then
        load_env --file="$rx9060xt_env" rx9060xt_vfio_once
        if [ "$rx9060xt_vfio_once" = 1 ]; then
            set rx9060xt_vfio_once=0
            if save_env --file="$rx9060xt_env" rx9060xt_vfio_once; then
                set default="{ENTRY}"
                set timeout=5
            fi
        fi
    fi
fi
'''
    state = {'backup': str(backup), 'boot_id_before': boot_id, 'normal_hashes': original_images, 'status': 'preparing', 'one_shot_armed': False}
    STATE.write_text(json.dumps(state, indent=2))
    try:
        conf = Path('/etc/mkinitcpio.conf').read_text()
        conf, count = re.subn(r'^MODULES=\(\)', 'MODULES=(vfio_pci vfio vfio_iommu_type1)', conf, flags=re.M)
        assert count == 1, 'MODULES inatteso'
        write(CONF, conf)
        run('mkinitcpio', '-c', str(CONF), '-k', '/boot/vmlinuz-linux-cachyos', '-g', str(IMAGE))
        listing = run('lsinitcpio', str(IMAGE), capture_output=True).stdout
        assert 'vfio-pci.ko' in listing and 'amdgpu.ko' in listing
        write(ONCE, once, 0o755)
        write(MENU, menu, 0o755)
        ENV.parent.mkdir(parents=True, exist_ok=True)
        run('grub-editenv', str(ENV), 'create')
        run('grub-editenv', str(ENV), 'set', 'rx9060xt_vfio_once=0')
        candidate = backup / 'grub.cfg.candidate'
        run('grub-mkconfig', '-o', str(candidate))
        run('grub-script-check', str(candidate))
        generated = candidate.read_text()
        assert normal in generated, 'La voce Linux normale è cambiata: non installare'
        old_windows = [s for s in old_cfg.splitlines() if s.lstrip().startswith('menuentry ') and 'Windows' in s]
        assert all(s in generated for s in old_windows), 'Voce Windows mancante: non installare'
        assert generated.count('--id ' + "'" + ENTRY + "'") == 1
        write(ACCESS, ACCESS_TEXT, 0o755)
        write(UNIT, '''[Unit]
Description=Access to isolated RX9060XT VFIO groups on the explicit test boot
After=local-fs.target systemd-udev-settle.service
ConditionKernelCommandLine=rx9060xt_vfio_test=1
[Service]
Type=oneshot
ExecStart=/usr/local/sbin/rx9060xt-vfio-access.py
[Install]
WantedBy=multi-user.target
''')
        run('systemctl', 'daemon-reload')
        run('systemctl', 'enable', UNIT.name)
        # Replace only after syntax, menu-preservation and original-image checks.
        assert all(digest(Path(p)) == h for p, h in original_images.items())
        shutil.copy2(candidate, CFG.with_suffix('.cfg.rx9060xt-new'))
        os.replace(CFG.with_suffix('.cfg.rx9060xt-new'), CFG)
        state.update(status='prepared', initramfs_sha256=digest(IMAGE), grub_cfg_sha256=digest(CFG))
        STATE.write_text(json.dumps(state, indent=2))
        print(json.dumps(state, indent=2))
    except BaseException:
        shutil.copy2(backup / 'grub.cfg', CFG)
        subprocess.run(['systemctl', 'disable', UNIT.name], capture_output=True)
        for path in (ENV, IMAGE, CONF, ONCE, MENU, ACCESS, UNIT):
            path.unlink(missing_ok=True)
        subprocess.run(['systemctl', 'daemon-reload'])
        state['status'] = 'failed-and-restored'
        STATE.write_text(json.dumps(state, indent=2))
        raise


def arm():
    state = json.loads(STATE.read_text())
    assert state['status'] == 'prepared'
    assert digest(IMAGE) == state['initramfs_sha256'] and digest(CFG) == state['grub_cfg_sha256']
    assert all(digest(Path(p)) == h for p, h in state['normal_hashes'].items())
    run('grub-editenv', str(ENV), 'set', 'rx9060xt_vfio_once=1')
    assert 'rx9060xt_vfio_once=1' in run('grub-editenv', str(ENV), 'list', capture_output=True).stdout
    state['one_shot_armed'] = True
    STATE.write_text(json.dumps(state, indent=2))
    run('sync')
    print('Prossimo avvio VFIO armato; Linux normale rimane il default successivo.')


def rollback():
    state = json.loads(STATE.read_text())
    assert state['status'] == 'prepared'
    assert digest(CFG) == state['grub_cfg_sha256'], 'GRUB cambiato successivamente: non ripristinare una copia obsoleta'
    assert all(digest(Path(p)) == h for p, h in state['normal_hashes'].items()), 'Kernel o configurazione cambiati: richiede ripristino aggiornato'
    run('grub-editenv', str(ENV), 'set', 'rx9060xt_vfio_once=0')
    run('systemctl', 'disable', UNIT.name)
    shutil.copy2(Path(state['backup']) / 'grub.cfg', CFG)
    for path in (ENV, IMAGE, CONF, ONCE, MENU, ACCESS, UNIT):
        path.unlink(missing_ok=True)
    run('systemctl', 'daemon-reload')
    state.update(status='rolled-back', one_shot_armed=False)
    STATE.write_text(json.dumps(state, indent=2))
    print('Configurazione di avvio originale ripristinata; nessun binding live cambiato.')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['prepare', 'arm', 'disarm', 'rollback'])
    args = parser.parse_args()
    validate_host()
    if args.action == 'prepare':
        prepare()
    elif args.action == 'arm':
        arm()
    elif args.action == 'rollback':
        rollback()
    else:
        run('grub-editenv', str(ENV), 'set', 'rx9060xt_vfio_once=0')
        state = json.loads(STATE.read_text())
        state['one_shot_armed'] = False
        STATE.write_text(json.dumps(state, indent=2))
        print('Avvio VFIO disarmato.')
