@echo off
setlocal enabledelayedexpansion

:: Get the system time before synchronization
for /f "tokens=2 delims==" %%a in ('"wmic os get localdatetime /value"') do set "before_sync_time=%%a"
set "before_sync_time=!before_sync_time:~0,4!-!before_sync_time:~4,2!-!before_sync_time:~6,2! !before_sync_time:~8,2!:!before_sync_time:~10,2!:!before_sync_time:~12,2!"

:: Synchronize system time with a time server
w32tm /resync

:: Wait for a few seconds to allow time for the sync to occur
ping localhost -n 5 > nul

:: Get the system time after synchronization
for /f "tokens=2 delims==" %%a in ('"wmic os get localdatetime /value"') do set "after_sync_time=%%a"
set "after_sync_time=!after_sync_time:~0,4!-!after_sync_time:~4,2!-!after_sync_time:~6,2! !after_sync_time:~8,2!:!after_sync_time:~10,2!:!after_sync_time:~12,2!"

:: Calculate the time deviation (in seconds)
:: Note: This is a simple calculation and may not be very accurate
set /a "before_epoch = (%before_sync_time:~0,4% - 1970) * 31536000 + (%before_sync_time:~5,2% * 2592000) + (%before_sync_time:~8,2% * 86400) + (%before_sync_time:~11,2% * 3600) + (%before_sync_time:~14,2% * 60) + %before_sync_time:~17,2%"
set /a "after_epoch = (%after_sync_time:~0,4% - 1970) * 31536000 + (%after_sync_time:~5,2% * 2592000) + (%after_sync_time:~8,2% * 86400) + (%after_sync_time:~11,2% * 3600) + (%after_sync_time:~14,2% * 60) + %after_sync_time:~17,2%"
set /a "time_deviation = after_epoch - before_epoch"

:: Report the times and the deviation
echo Time before sync: %before_sync_time%
echo Time after sync: %after_sync_time%
echo Time deviation: %time_deviation%s

endlocal
