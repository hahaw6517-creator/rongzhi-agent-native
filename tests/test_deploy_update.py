"""Exercise deployment orchestration with fake Docker/Git; never touch a server."""
import os
from pathlib import Path
import shutil
import subprocess

import pytest

BASH = shutil.which('bash') or ('C:/Program Files/Git/bin/bash.exe' if Path('C:/Program Files/Git/bin/bash.exe').exists() else None)
pytestmark = pytest.mark.skipif(not BASH, reason='Bash is required for deployment-script tests')

GIT = '''#!/usr/bin/env bash
echo "git $*" >> "$DEPLOY_TEST_ROOT/events"
case "$1" in
 branch) echo main ;;
 diff) [[ "$DEPLOY_TEST_MODE" != dirty ]] ;;
 remote) echo https://github.com/hahaw6517-creator/rongzhi-agent-native.git ;;
 fetch|merge) [[ "$DEPLOY_TEST_MODE" != fetch_failure ]] ;;
 rev-parse) if [[ "$2" == --git-path ]]; then echo .git/update.lock; else echo testrevision; fi ;;
 *) exit 1 ;;
esac
'''

DOCKER = '''#!/usr/bin/env bash
echo "docker $*" >> "$DEPLOY_TEST_ROOT/events"
case "$1" in
 compose)
   if [[ " $* " == *" up "* ]]; then
     tag=$(cat "$DEPLOY_TEST_ROOT/tag")
     [[ "$DEPLOY_TEST_MODE" == recreate_failure && "$tag" == new ]] && exit 1
     echo "$tag" > "$DEPLOY_TEST_ROOT/running"
   fi
   ;;
 inspect)
   case "$3" in
     *State.Running*) echo true ;;
     *project.working_dir*) echo "$DEPLOY_TEST_ROOT/original-deploy" ;;
     *project.config_files*) echo "$DEPLOY_TEST_ROOT/original-deploy/compose.yml" ;;
     *compose.project*) echo existingproject ;;
     *compose.service*) echo agent ;;
     *Config.Image*) echo finbridge:latest ;;
     *Mounts*) echo volume:existing-data:/volumes/existing-data ;;
     *Image*) echo "sha256:$(cat "$DEPLOY_TEST_ROOT/running")" ;;
     *) exit 1 ;;
   esac
   ;;
 exec)
   if [[ "$2" == -i ]]; then
     cat >/dev/null
     [[ "$DEPLOY_TEST_MODE" != backup_failure ]] || exit 1
     echo /app/storage/.update-backups/test.sqlite3
   elif [[ "$DEPLOY_TEST_MODE" == health_failure && "$(cat "$DEPLOY_TEST_ROOT/running")" == new ]]; then
     exit 1
   fi
   ;;
 cp) touch "$3" ;;
 build)
   [[ "$DEPLOY_TEST_MODE" != build_failure ]] || exit 1
   echo new > "$DEPLOY_TEST_ROOT/tag"
   ;;
 image)
   if [[ "$2" == inspect ]]; then echo sha256:new; else echo old > "$DEPLOY_TEST_ROOT/tag"; fi
   ;;
 *) exit 1 ;;
esac
'''


def exercise(tmp_path, mode):
    (tmp_path/'deploy').mkdir()
    (tmp_path/'.git').mkdir()
    (tmp_path/'bin').mkdir()
    (tmp_path/'original-deploy').mkdir()
    (tmp_path/'original-deploy'/'compose.yml').write_text('original-compose')
    (tmp_path/'original-deploy'/'.env').write_text('test-only-secret')
    shutil.copyfile('deploy/update.sh', tmp_path/'deploy'/'update.sh')
    for name, body in {'git':GIT,'docker':DOCKER,'flock':'#!/usr/bin/env bash\nexit 0\n','sleep':'#!/usr/bin/env bash\nexit 0\n'}.items():
        script=tmp_path/'bin'/name
        script.write_text(body,encoding='utf-8',newline='\n');script.chmod(0o755)
    (tmp_path/'tag').write_text('old');(tmp_path/'running').write_text('old')
    env={**os.environ,'DEPLOY_TEST_MODE':mode}
    result=subprocess.run([BASH,'-c','export DEPLOY_TEST_ROOT="$PWD"; export PATH="$PWD/bin:$PATH"; bash deploy/update.sh'],cwd=tmp_path,env=env,text=True,encoding='utf-8',capture_output=True,timeout=30)
    assert (tmp_path/'original-deploy'/'compose.yml').read_text()=='original-compose'
    assert (tmp_path/'original-deploy'/'.env').read_text()=='test-only-secret'
    events=(tmp_path/'events').read_text(encoding='utf-8')
    assert 'down' not in events
    return result,events,(tmp_path/'running').read_text().strip()


def test_update_builds_and_recreates_original_project_after_backup(tmp_path):
    result,events,running=exercise(tmp_path,'success')
    assert result.returncode==0,result.stdout+result.stderr
    assert running=='new' and 'Updated successfully: testrevision' in result.stdout
    assert events.index('git fetch')<events.index('docker cp')<events.index('docker build')
    assert '-p existingproject' in events and '--pull never --force-recreate agent' in events
    assert list((tmp_path/'tmp'/'server-backups').glob('*/runtime.sqlite3'))


@pytest.mark.parametrize('mode',['dirty','fetch_failure','backup_failure','build_failure'])
def test_preflight_or_build_failure_keeps_old_container(tmp_path,mode):
    result,events,running=exercise(tmp_path,mode)
    assert result.returncode!=0 and running=='old'
    assert ' up -d ' not in events


@pytest.mark.parametrize('mode',['recreate_failure','health_failure'])
def test_failed_replacement_restores_previous_image(tmp_path,mode):
    result,events,running=exercise(tmp_path,mode)
    assert result.returncode!=0 and running=='old',result.stdout+result.stderr
    assert 'docker image tag sha256:old finbridge:latest' in events
    assert 'Previous image restored' in result.stderr
