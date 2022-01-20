#!/bin/bash
main()
{
    while true; do
        . /home/bernerus/SM6FBQ/StnMate2/etc/server_monitor.conf
        start=`perl -e 'print time();'`
        startserver
        end=`perl -e 'print time();'`
        lapsed=`expr $end - $start`
        if [ "${lapsed}" -lt "${DAEMONWAIT}" ]; then
            /usr/bin/mailx -s "StnMate2 server short run" ${DEVELOPERMAIL} <<EOF
The StnMate2 server died after running for only $lapsed seconds. Will retry in $LONGWAIT seconds.

Here are the last 50 lines of the output file:
----------------------------------------------
`tail -50 ${OUTFILE}`
EOF
            sleep $LONGWAIT
        else
            /usr/bin/mailx -s "StnMate2 server died" ${DEVELOPERMAIL} <<EOF
The MIDAS server has died after a long time. Restarting in 15 seconds.

Here are the last 50 lines of the output file:
----------------------------------------------
`tail -50 ${OUTFILE}`
EOF
	   sleep 15
        fi
    done
}

startserver()
{
    startmsg="`date '+%F %T'` StnMate2 server started"
    echo "$startmsg" >> ${OUTFILE}

    /home/bernerus/SM6FBQ/StnMate2/etc/startserver.sh </dev/null >>${OUTFILE} 2>&1

    endmsg="`date '+%F %T'` StnMate2 server terminated"
    echo "$endmsg" >> ${OUTFILE}
}

main
