"""Task definitions for the sample project."""

from datetime import timedelta

from plx.framework._task import task

from . import MainProgram

main_task = task("MainTask", periodic=timedelta(milliseconds=10), pous=[MainProgram], priority=1)
