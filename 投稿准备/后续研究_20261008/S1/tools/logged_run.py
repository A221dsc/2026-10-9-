"""Record the actual exit of a long-running orchestration subprocess."""
from pathlib import Path
import argparse
import os
import subprocess
import time
from dev_launch import dump

def run_logged(command,root):
    root=Path(root).resolve();root.mkdir(parents=True,exist_ok=False)
    command=[str(x) for x in command];started=time.time_ns()
    with (root/'stdout.txt').open('xb',buffering=0) as stdout, (root/'stderr.txt').open('xb',buffering=0) as stderr:
        child=subprocess.Popen(command,stdin=subprocess.DEVNULL,stdout=stdout,stderr=stderr)
        dump(root/'launched.json',{'command':command,'started_ns':started,'child_pid':child.pid,'supervisor_pid':os.getpid()})
        code=child.wait()
    dump(root/'process.json',{'command':command,'started_ns':started,'ended_ns':time.time_ns(),
                            'child_pid':child.pid,'exit_code':code,'actual_exit_observed':True})
    return code

def main():
    p=argparse.ArgumentParser();p.add_argument('--output',required=True);p.add_argument('command',nargs=argparse.REMAINDER)
    a=p.parse_args();command=a.command[1:] if a.command and a.command[0]=='--' else a.command
    if not command:p.error('subprocess command required after --')
    raise SystemExit(run_logged(command,a.output))

if __name__=='__main__':main()
