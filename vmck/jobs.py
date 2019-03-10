import logging
from django.conf import settings
from .models import Job
from . import nomad

log_level = logging.DEBUG
log = logging.getLogger(__name__)
log.setLevel(log_level)


def nomad_id(job):
    prefix = settings.NOMAD_JOB_PREFIX
    return f'{prefix}{job.id}'


def create(backend):
    job = Job.objects.create()

    nomad.launch(
        nomad.job(
            id=nomad_id(job),
            name=f"{settings.NOMAD_DEPLOYMENT_NAME} job #{job.id}",
            taskgroups=[backend.task_group()],
        ),
    )

    job.state = job.STATE_RUNNING
    job.save()

    return job


def sync_artifacts(job):
    job.artifact_set.all().delete()
    for name in ['stdout.txt', 'stderr.txt']:
        data = nomad.cat(nomad_id(job), f'alloc/data/{name}', binary=True)
        if data is not None:
            job.artifact_set.create(name=name, data=data)


def dump_logs(job):
    for jobname in ['control', 'vm']:
        for filename in ['stdout', 'stderr']:
            filepath = f'alloc/logs/{jobname}.{filename}.0'
            data = nomad.cat(nomad_id(job), filepath)
            if data:
                log.debug('=== %s ===\n%s', filepath, data)
            else:
                log.debug('%s is empty', filepath)


def on_done(job):
    dump_logs(job)
    sync_artifacts(job)
    job.state = job.STATE_DONE
    job.save()


def poll(job):
    status = nomad.status(nomad_id(job))
    log.debug('%r status: %r', job, status)

    if status in [None, 'pending']:
        return

    elif status == 'running':
        job.state = job.STATE_RUNNING
        done = nomad.cat(nomad_id(job), f'alloc/data/done', binary=True)
        if done is not None:
            on_done(job)
            kill(job)

    elif status in ['complete', 'failed']:
        on_done(job)

    else:
        raise RuntimeError(f"Unknown status {status!r}")


def kill(job):
    nomad.kill(nomad_id(job))
