/* B840: disable USB PME only for Darwin S5, preserving original _PTS.
 * Requires the exact DSDT-only _PTS -> ZPTS rename in the accompanying recipe.
 * PCI PM capability offsets and device IDs were read from the running IORegistry.
 * Identity + capability-ID checks precede every PME_Enable write.
 * Candidate: effectiveness against this board's power-on-after-S5 is unverified.
 */
DefinitionBlock ("", "SSDT", 2, "NAVI44", "USB-S5", 0x00000001)
{
    External (\ZPTS, MethodObj)
    External (\_SB.PCI0.GPP7.XH00, DeviceObj)
    External (\_SB.PCI0.GP17.XHC0, DeviceObj)
    External (\_SB.PCI0.GP17.XHC1, DeviceObj)
    External (\_SB.PCI0.GP19.XHC2, DeviceObj)
    External (\_SB.PCI0.GPP7.XH00.N4S5, MethodObj)
    External (\_SB.PCI0.GP17.XHC0.N4S5, MethodObj)
    External (\_SB.PCI0.GP17.XHC1.N4S5, MethodObj)
    External (\_SB.PCI0.GP19.XHC2.N4S5, MethodObj)
    Method (_PTS, 1, NotSerialized)
    {
        ZPTS (Arg0)
        If (LAnd (_OSI ("Darwin"), LEqual (Arg0, 0x05)))
        {
            \_SB.PCI0.GPP7.XH00.N4S5 ()
            \_SB.PCI0.GP17.XHC0.N4S5 ()
            \_SB.PCI0.GP17.XHC1.N4S5 ()
            \_SB.PCI0.GP19.XHC2.N4S5 ()
        }
    }
    Scope (\_SB.PCI0.GPP7.XH00)
    {
        OperationRegion (N4CF, PCI_Config, Zero, 0x0100)
        Field (N4CF, ByteAcc, NoLock, Preserve)
        {
            N4VI, 16,
            N4DI, 16,
            Offset (0x78),
            N4CI, 8,
            Offset (0x7D),
            N4PE, 1
        }
        Method (N4S5, 0, Serialized)
        {
            If (LAnd (LEqual (N4VI, 0x1022),
                LAnd (LEqual (N4DI, 0x43EF), LEqual (N4CI, One))))
            {
                N4PE = Zero
                Return (One)
            }
            Return (Zero)
        }
    }
    Scope (\_SB.PCI0.GP17.XHC0)
    {
        OperationRegion (N4CF, PCI_Config, Zero, 0x0100)
        Field (N4CF, ByteAcc, NoLock, Preserve)
        {
            N4VI, 16,
            N4DI, 16,
            Offset (0x50),
            N4CI, 8,
            Offset (0x55),
            N4PE, 1
        }
        Method (N4S5, 0, Serialized)
        {
            If (LAnd (LEqual (N4VI, 0x1022),
                LAnd (LEqual (N4DI, 0x15B6), LEqual (N4CI, One))))
            {
                N4PE = Zero
                Return (One)
            }
            Return (Zero)
        }
    }
    Scope (\_SB.PCI0.GP17.XHC1)
    {
        OperationRegion (N4CF, PCI_Config, Zero, 0x0100)
        Field (N4CF, ByteAcc, NoLock, Preserve)
        {
            N4VI, 16,
            N4DI, 16,
            Offset (0x50),
            N4CI, 8,
            Offset (0x55),
            N4PE, 1
        }
        Method (N4S5, 0, Serialized)
        {
            If (LAnd (LEqual (N4VI, 0x1022),
                LAnd (LEqual (N4DI, 0x15B7), LEqual (N4CI, One))))
            {
                N4PE = Zero
                Return (One)
            }
            Return (Zero)
        }
    }
    Scope (\_SB.PCI0.GP19.XHC2)
    {
        OperationRegion (N4CF, PCI_Config, Zero, 0x0100)
        Field (N4CF, ByteAcc, NoLock, Preserve)
        {
            N4VI, 16,
            N4DI, 16,
            Offset (0x50),
            N4CI, 8,
            Offset (0x55),
            N4PE, 1
        }
        Method (N4S5, 0, Serialized)
        {
            If (LAnd (LEqual (N4VI, 0x1022),
                LAnd (LEqual (N4DI, 0x15B8), LEqual (N4CI, One))))
            {
                N4PE = Zero
                Return (One)
            }
            Return (Zero)
        }
    }
}
