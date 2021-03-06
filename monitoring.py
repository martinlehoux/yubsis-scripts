# -*- coding: utf-8 -*-
import shutil
import unittest
import os
import sys
import re
from operator import itemgetter
try:
    import apt
except ImportError:
    apt = None

from mail import Email
from conf import BACKUP_ROOT_PROD, DISK_PARTITIONS, LOG_PATH


def sizeof_fmt(num, suffix='B'):
    for unit in ['','Ki','Mi','Gi','Ti','Pi','Ei','Zi']:
        if abs(num) < 1024.0:
            return "%3.1f %s%s" % (num, unit, suffix)
        num /= 1024.0
    return "%.1f%s%s" % (num, 'Yi', suffix)

class Module:
    title = None
    headers = None
    platforms = ['linux', 'darwin']

    @classmethod
    def make_table(cls, data):
        """
        Args:
            data (list(list(str))) Each line must be the same len as headers
        Returns:
            body (str)
            plain (str)
        """
        body = "<h1>{}</h1>".format(cls.title)
        plain = cls.title + '\n' + '='*len(cls.title) + '\n'
        body += "<table><thead><tr>"
        for header in cls.headers:
            body += "<th>{}</th>".format(header)
            plain += header + ", "
        body += "</tr></thead><tbody>"
        plain += "\n"
        for line in data:
            assert len(line) == len(cls.headers)
            body += "<tr>"
            for item in line:
                body += "<td>{}</td>".format(item)
                plain += str(item) + ", "
            body += "</tr>"
            plain += "\n"
        body += "</tbody></table>"
        plain += "\n"
        return body, plain

    @staticmethod
    def get_data():
        raise NotImplementedError

class DiskModule(Module):
    title = 'Espace disque'
    headers = ['Partition', 'Used', 'Total', 'Percent']

    @staticmethod
    def get_data():
        data = []
        used = 0
        for part in DISK_PARTITIONS:
            disk_usage = shutil.disk_usage(part)
            used += disk_usage.used
            data.append([
                part,
                sizeof_fmt(disk_usage.used),
                '',
                "{:.2%}".format(disk_usage.used / disk_usage.total)
            ])
        data.append([
            'TOTAL',
            sizeof_fmt(used),
            sizeof_fmt(disk_usage.total),
            "{:.2%}".format(used / disk_usage.total)
        ])
        return data

class AptModule(Module):
    title = 'Mises à jour'
    headers = ['Nom', 'Installé', 'Disponible']
    platforms = ['linux']

    @staticmethod
    def get_data():
        data = []
        cache = apt.Cache()
        cache.update()
        for pkg in cache:
            if pkg.is_upgradable:
                data.append([pkg.name, pkg.installed, pkg.candidate])
        return data


class LogModule(Module):
    title = 'Fichiers logs'
    headers = ['Nom', 'Nombre de fichiers', 'Taille']
    log_path = LOG_PATH
    MAX_ENTRIES = 10
    MIN_SIZE = 1000

    @staticmethod
    def get_base_name(filename):
        reg = r"(.*).log(\.[0-9])?(\.gz)?(\.bz2)?"
        result = re.match(reg, filename)
        return result and result.groups()[0]

    @staticmethod
    def get_data():
        data = []
        log_files = os.scandir(LogModule.log_path)
        logs = dict()
        for file in log_files:
            if file.is_file():
                basename = LogModule.get_base_name(file.name)
                if not logs.get(basename):
                    logs[basename] = dict(total_size=0, file_number=0)
                logs[basename]['total_size'] += file.stat().st_size
                logs[basename]['file_number'] += 1
        for logname, info in logs.items():
            data.append([
                logname,
                info['file_number'],
                info['total_size'],
            ])
        data = list(reversed(sorted(data, key=itemgetter(2))))
        final_data = []
        for item in data:
            new_item = item.copy()
            if item[2] < LogModule.MIN_SIZE:
                continue
            if len(final_data) >= LogModule.MAX_ENTRIES:
                break
            new_item[2] = sizeof_fmt(item[2])
            final_data.append(new_item)
        final_data.append(["Total", sum([it[1] for it in data]), sizeof_fmt(sum([it[2] for it in data]))])
        return final_data

MODULES = Module.__subclasses__()


class MEmail(Email):
    backup_root = BACKUP_ROOT_PROD
    title = "Rapport de monitoring"


if __name__ == "__main__":
    message = MEmail()
    body, plain = "", ""
    for module in MODULES:
        if sys.platform in module.platforms:
            _body, _plain = module.make_table(module.get_data())
            body += _body
            plain += _plain
        else:
            print("[{}] module not supported on {}".format(module.title, sys.platform))
    print(plain)
    message.attach_all(body, plain)
    message.send()


class LogModuleTest(unittest.TestCase):
    def setUp(self):
        LogModule.log_path = os.path.join(os.path.dirname(__file__), "logs-test")
        os.makedirs(LogModule.log_path, exist_ok=True)
        for i in range(1, 10):
            with open(os.path.join(LogModule.log_path, "logfile.log.{}.gz".format(i)), "w") as file:
                file.write("aaaa" * i * 100)
        with open(os.path.join(LogModule.log_path, "logfile.log"), "w") as file:
                file.write("hey")

    def tearDown(self):
        shutil.rmtree(LogModule.log_path)

    def test_get_base_name(self):
        self.assertEqual(LogModule.get_base_name('fsck_apfs_error.log'), 'fsck_apfs_error')
        self.assertEqual(LogModule.get_base_name('fsck_apfs_error.log.gz'), 'fsck_apfs_error')
        self.assertEqual(LogModule.get_base_name('fsck_apfs_error.log.8.bz2'), 'fsck_apfs_error')
        self.assertEqual(LogModule.get_base_name('fsck.apfs_error.log.3.gz'), 'fsck.apfs_error')

    def test_get_data(self):
        data = LogModule.get_data()
        self.assertEqual(data[0], ['logfile', 10, '17.6 KiB'])
        self.assertEqual(data[1], ['Total', 10, '17.6 KiB'])
