turin-cosmo-1.0.0.7.mbist-mfg-v0-dext-len3.efs.json5 :  15min test, DataEye XT enabled
tom@jeeves:/staff/tom/git/dmar-report $ grep Mbist turin-cosmo-1.0.0.7.mbist-mfg-v0-dext-len3.efs.json5
                        MemMbistAggressorStaticLaneControl: false
                        MemMbistTgtStaticLaneControl: false
                        MemMbistAggressorsChannelDdrMode: "SubChannel"
                        MemMbistPatternLengthDdr: 3
                        MemMbistWorseCasGranularity: 0
                        MemMbistReadDataEyeVoltageStep: 1
                        MemMbistPerBitSlaveDieReportDdr: "Auto"
                        MemMbistAggressorStaticLaneVal: 0
                        MemMbistTgtStaticLaneVal: 0
                        MemMbistDataEyeType: "1D Timing"
                        MemMbistAggressorStaticLaneSelEcc: 0
                        MemMbistReadDataEyeTimingStep: 1
                        MemMbistPatternSelectDdr: "Prbs"
                        MemMbistDdrMode: "Disabled"
                        MemMbistDataEyeSilentExecutionDdr: "Enabled"
                        BdatSupport: "Enabled"    // 'Enabled' for Mbist
                        MemMbistDataEyeExecutionRepeatCount: 1
                        MemMbistTestModeDdr: "DataEye"
                        MemMbistTgtStaticLaneSelEcc: 0
                        MemMbistHaltOnError: 1
                        MemMbistAggressorsDdr: "Enabled"
                        MemMbistWriteDataEyeVoltageStep: 1
                        MemMbistWriteDataEyeTimingStep: 1
                        MemMbistAggressorStaticLaneSelLo: 0
                        MemMbistTgtStaticLaneSelLo: 0
                        MemMbistTgtStaticLaneSelHi: 0
                        MemMbistAggressorStaticLaneSelHi: 0


turin-cosmo-1.0.0.7.mbist-mfg-v1-qxt-len3.efs.json5  :  20min
tom@jeeves:/staff/tom/git/dmar-report $ diff <(grep Mbist turin-cosmo-1.0.0.7.mbist-mfg-v0-dext-len3.efs.json5 ) <(grep Mbist turin-cosmo-1.0.0.7.mbist-mfg-v1-qxt-len3.efs.json5 )
18c18
<                         MemMbistTestModeDdr: "DataEye"
---
>                         MemMbistTestModeDdr: "Auto"









turin-cosmo-1.0.0.7.mbist-mfg-v2-full-xt-len3.efs.json5  : 30min full xt len3
tom@jeeves:/staff/tom/git/dmar-report $ diff <(grep Mbist turin-cosmo-1.0.0.7.mbist-mfg-v1-qxt-len3.efs.json5) <(grep Mbist turin-cosmo-1.0.0.7.mbist-mfg-v2-full-xt-len3.efs.json5 )
3c3
<                         MemMbistAggressorsChannelDdrMode: "SubChannel"
---
>                         MemMbistAggressorsChannelDdrMode: "All"
13c13
<                         MemMbistPatternSelectDdr: "Prbs"
---
>                         MemMbistPatternSelectDdr: "Both"
18c18
<                         MemMbistTestModeDdr: "Auto"
---
>                         MemMbistTestModeDdr: "Both"




