/* Synthetic ACPICA-only fixture: operation regions are simulated by acpiexec. */
DefinitionBlock ("", "DSDT", 2, "NAVI44", "S5TEST", 1)
{
Name (CNT, Zero)
Method (ZPTS, 1) { CNT = Arg0 }
Scope (_SB) { Device (PCI0) { Name (_HID, EisaId ("PNP0A08"))
Device (GPP7) { Name (_ADR, 0x00020001) Device (XH00) { Name (_ADR, Zero) } }
Device (GP17) { Name (_ADR, 0x00080001) Device (XHC0) { Name (_ADR, 0x03) } Device (XHC1) { Name (_ADR, 0x04) } }
Device (GP19) { Name (_ADR, 0x00080003) Device (XHC2) { Name (_ADR, Zero) } }
} }
External (_PTS, MethodObj)
External (\_SB.PCI0.GPP7.XH00.N4VI, FieldUnitObj)
External (\_SB.PCI0.GPP7.XH00.N4DI, FieldUnitObj)
External (\_SB.PCI0.GPP7.XH00.N4CI, FieldUnitObj)
External (\_SB.PCI0.GPP7.XH00.N4S5, MethodObj)
External (\_SB.PCI0.GPP7.XH00.N4CS, FieldUnitObj)
External (\_SB.PCI0.GP17.XHC0.N4VI, FieldUnitObj)
External (\_SB.PCI0.GP17.XHC0.N4DI, FieldUnitObj)
External (\_SB.PCI0.GP17.XHC0.N4CI, FieldUnitObj)
External (\_SB.PCI0.GP17.XHC0.N4S5, MethodObj)
External (\_SB.PCI0.GP17.XHC0.N4CS, FieldUnitObj)
External (\_SB.PCI0.GP17.XHC1.N4VI, FieldUnitObj)
External (\_SB.PCI0.GP17.XHC1.N4DI, FieldUnitObj)
External (\_SB.PCI0.GP17.XHC1.N4CI, FieldUnitObj)
External (\_SB.PCI0.GP17.XHC1.N4S5, MethodObj)
External (\_SB.PCI0.GP17.XHC1.N4CS, FieldUnitObj)
External (\_SB.PCI0.GP19.XHC2.N4VI, FieldUnitObj)
External (\_SB.PCI0.GP19.XHC2.N4DI, FieldUnitObj)
External (\_SB.PCI0.GP19.XHC2.N4CI, FieldUnitObj)
External (\_SB.PCI0.GP19.XHC2.N4S5, MethodObj)
External (\_SB.PCI0.GP19.XHC2.N4CS, FieldUnitObj)
Method (TV00, 0, Serialized) {
\_SB.PCI0.GPP7.XH00.N4VI = 0x1022
\_SB.PCI0.GPP7.XH00.N4DI = 0x43EF
\_SB.PCI0.GPP7.XH00.N4CI = 0x1
\_SB.PCI0.GPP7.XH00.N4CS = 0xABCD
Local0 = \_SB.PCI0.GPP7.XH00.N4S5 ()
If (LNotEqual (Local0, 1)) { Return (One) }
If (LNotEqual (\_SB.PCI0.GPP7.XH00.N4CS, 0xAACD)) { Return (0x02) }
Return (Zero)
}
Method (TD00, 0, Serialized) {
\_SB.PCI0.GPP7.XH00.N4VI = 0x1022
\_SB.PCI0.GPP7.XH00.N4DI = 0xFFFF
\_SB.PCI0.GPP7.XH00.N4CI = 0x1
\_SB.PCI0.GPP7.XH00.N4CS = 0xABCD
Local0 = \_SB.PCI0.GPP7.XH00.N4S5 ()
If (LNotEqual (Local0, 0)) { Return (One) }
If (LNotEqual (\_SB.PCI0.GPP7.XH00.N4CS, 0xABCD)) { Return (0x02) }
Return (Zero)
}
Method (TC00, 0, Serialized) {
\_SB.PCI0.GPP7.XH00.N4VI = 0x1022
\_SB.PCI0.GPP7.XH00.N4DI = 0x43EF
\_SB.PCI0.GPP7.XH00.N4CI = 0x2
\_SB.PCI0.GPP7.XH00.N4CS = 0xABCD
Local0 = \_SB.PCI0.GPP7.XH00.N4S5 ()
If (LNotEqual (Local0, 0)) { Return (One) }
If (LNotEqual (\_SB.PCI0.GPP7.XH00.N4CS, 0xABCD)) { Return (0x02) }
Return (Zero)
}
Method (TF00, 0, Serialized) {
\_SB.PCI0.GPP7.XH00.N4VI = 0xFFFF
\_SB.PCI0.GPP7.XH00.N4DI = 0x43EF
\_SB.PCI0.GPP7.XH00.N4CI = 0x1
\_SB.PCI0.GPP7.XH00.N4CS = 0xABCD
Local0 = \_SB.PCI0.GPP7.XH00.N4S5 ()
If (LNotEqual (Local0, 0)) { Return (One) }
If (LNotEqual (\_SB.PCI0.GPP7.XH00.N4CS, 0xABCD)) { Return (0x02) }
Return (Zero)
}
Method (TV01, 0, Serialized) {
\_SB.PCI0.GP17.XHC0.N4VI = 0x1022
\_SB.PCI0.GP17.XHC0.N4DI = 0x15B6
\_SB.PCI0.GP17.XHC0.N4CI = 0x1
\_SB.PCI0.GP17.XHC0.N4CS = 0xABCD
Local0 = \_SB.PCI0.GP17.XHC0.N4S5 ()
If (LNotEqual (Local0, 1)) { Return (One) }
If (LNotEqual (\_SB.PCI0.GP17.XHC0.N4CS, 0xAACD)) { Return (0x02) }
Return (Zero)
}
Method (TD01, 0, Serialized) {
\_SB.PCI0.GP17.XHC0.N4VI = 0x1022
\_SB.PCI0.GP17.XHC0.N4DI = 0xFFFF
\_SB.PCI0.GP17.XHC0.N4CI = 0x1
\_SB.PCI0.GP17.XHC0.N4CS = 0xABCD
Local0 = \_SB.PCI0.GP17.XHC0.N4S5 ()
If (LNotEqual (Local0, 0)) { Return (One) }
If (LNotEqual (\_SB.PCI0.GP17.XHC0.N4CS, 0xABCD)) { Return (0x02) }
Return (Zero)
}
Method (TC01, 0, Serialized) {
\_SB.PCI0.GP17.XHC0.N4VI = 0x1022
\_SB.PCI0.GP17.XHC0.N4DI = 0x15B6
\_SB.PCI0.GP17.XHC0.N4CI = 0x2
\_SB.PCI0.GP17.XHC0.N4CS = 0xABCD
Local0 = \_SB.PCI0.GP17.XHC0.N4S5 ()
If (LNotEqual (Local0, 0)) { Return (One) }
If (LNotEqual (\_SB.PCI0.GP17.XHC0.N4CS, 0xABCD)) { Return (0x02) }
Return (Zero)
}
Method (TF01, 0, Serialized) {
\_SB.PCI0.GP17.XHC0.N4VI = 0xFFFF
\_SB.PCI0.GP17.XHC0.N4DI = 0x15B6
\_SB.PCI0.GP17.XHC0.N4CI = 0x1
\_SB.PCI0.GP17.XHC0.N4CS = 0xABCD
Local0 = \_SB.PCI0.GP17.XHC0.N4S5 ()
If (LNotEqual (Local0, 0)) { Return (One) }
If (LNotEqual (\_SB.PCI0.GP17.XHC0.N4CS, 0xABCD)) { Return (0x02) }
Return (Zero)
}
Method (TV02, 0, Serialized) {
\_SB.PCI0.GP17.XHC1.N4VI = 0x1022
\_SB.PCI0.GP17.XHC1.N4DI = 0x15B7
\_SB.PCI0.GP17.XHC1.N4CI = 0x1
\_SB.PCI0.GP17.XHC1.N4CS = 0xABCD
Local0 = \_SB.PCI0.GP17.XHC1.N4S5 ()
If (LNotEqual (Local0, 1)) { Return (One) }
If (LNotEqual (\_SB.PCI0.GP17.XHC1.N4CS, 0xAACD)) { Return (0x02) }
Return (Zero)
}
Method (TD02, 0, Serialized) {
\_SB.PCI0.GP17.XHC1.N4VI = 0x1022
\_SB.PCI0.GP17.XHC1.N4DI = 0xFFFF
\_SB.PCI0.GP17.XHC1.N4CI = 0x1
\_SB.PCI0.GP17.XHC1.N4CS = 0xABCD
Local0 = \_SB.PCI0.GP17.XHC1.N4S5 ()
If (LNotEqual (Local0, 0)) { Return (One) }
If (LNotEqual (\_SB.PCI0.GP17.XHC1.N4CS, 0xABCD)) { Return (0x02) }
Return (Zero)
}
Method (TC02, 0, Serialized) {
\_SB.PCI0.GP17.XHC1.N4VI = 0x1022
\_SB.PCI0.GP17.XHC1.N4DI = 0x15B7
\_SB.PCI0.GP17.XHC1.N4CI = 0x2
\_SB.PCI0.GP17.XHC1.N4CS = 0xABCD
Local0 = \_SB.PCI0.GP17.XHC1.N4S5 ()
If (LNotEqual (Local0, 0)) { Return (One) }
If (LNotEqual (\_SB.PCI0.GP17.XHC1.N4CS, 0xABCD)) { Return (0x02) }
Return (Zero)
}
Method (TF02, 0, Serialized) {
\_SB.PCI0.GP17.XHC1.N4VI = 0xFFFF
\_SB.PCI0.GP17.XHC1.N4DI = 0x15B7
\_SB.PCI0.GP17.XHC1.N4CI = 0x1
\_SB.PCI0.GP17.XHC1.N4CS = 0xABCD
Local0 = \_SB.PCI0.GP17.XHC1.N4S5 ()
If (LNotEqual (Local0, 0)) { Return (One) }
If (LNotEqual (\_SB.PCI0.GP17.XHC1.N4CS, 0xABCD)) { Return (0x02) }
Return (Zero)
}
Method (TV03, 0, Serialized) {
\_SB.PCI0.GP19.XHC2.N4VI = 0x1022
\_SB.PCI0.GP19.XHC2.N4DI = 0x15B8
\_SB.PCI0.GP19.XHC2.N4CI = 0x1
\_SB.PCI0.GP19.XHC2.N4CS = 0xABCD
Local0 = \_SB.PCI0.GP19.XHC2.N4S5 ()
If (LNotEqual (Local0, 1)) { Return (One) }
If (LNotEqual (\_SB.PCI0.GP19.XHC2.N4CS, 0xAACD)) { Return (0x02) }
Return (Zero)
}
Method (TD03, 0, Serialized) {
\_SB.PCI0.GP19.XHC2.N4VI = 0x1022
\_SB.PCI0.GP19.XHC2.N4DI = 0xFFFF
\_SB.PCI0.GP19.XHC2.N4CI = 0x1
\_SB.PCI0.GP19.XHC2.N4CS = 0xABCD
Local0 = \_SB.PCI0.GP19.XHC2.N4S5 ()
If (LNotEqual (Local0, 0)) { Return (One) }
If (LNotEqual (\_SB.PCI0.GP19.XHC2.N4CS, 0xABCD)) { Return (0x02) }
Return (Zero)
}
Method (TC03, 0, Serialized) {
\_SB.PCI0.GP19.XHC2.N4VI = 0x1022
\_SB.PCI0.GP19.XHC2.N4DI = 0x15B8
\_SB.PCI0.GP19.XHC2.N4CI = 0x2
\_SB.PCI0.GP19.XHC2.N4CS = 0xABCD
Local0 = \_SB.PCI0.GP19.XHC2.N4S5 ()
If (LNotEqual (Local0, 0)) { Return (One) }
If (LNotEqual (\_SB.PCI0.GP19.XHC2.N4CS, 0xABCD)) { Return (0x02) }
Return (Zero)
}
Method (TF03, 0, Serialized) {
\_SB.PCI0.GP19.XHC2.N4VI = 0xFFFF
\_SB.PCI0.GP19.XHC2.N4DI = 0x15B8
\_SB.PCI0.GP19.XHC2.N4CI = 0x1
\_SB.PCI0.GP19.XHC2.N4CS = 0xABCD
Local0 = \_SB.PCI0.GP19.XHC2.N4S5 ()
If (LNotEqual (Local0, 0)) { Return (One) }
If (LNotEqual (\_SB.PCI0.GP19.XHC2.N4CS, 0xABCD)) { Return (0x02) }
Return (Zero)
}
Method (WR03, 0, Serialized) {
\_SB.PCI0.GPP7.XH00.N4VI = 0x1022
\_SB.PCI0.GPP7.XH00.N4DI = 0x43EF
\_SB.PCI0.GPP7.XH00.N4CI = One
\_SB.PCI0.GPP7.XH00.N4CS = 0xABCD
CNT = Zero
_PTS (0x3)
If (LNotEqual (CNT, 0x3)) { Return (One) }
If (LNotEqual (\_SB.PCI0.GPP7.XH00.N4CS, 0xABCD)) { Return (0x02) }
Return (Zero)
}
Method (WR05, 0, Serialized) {
\_SB.PCI0.GPP7.XH00.N4VI = 0x1022
\_SB.PCI0.GPP7.XH00.N4DI = 0x43EF
\_SB.PCI0.GPP7.XH00.N4CI = One
\_SB.PCI0.GPP7.XH00.N4CS = 0xABCD
CNT = Zero
_PTS (0x5)
If (LNotEqual (CNT, 0x5)) { Return (One) }
If (LNotEqual (\_SB.PCI0.GPP7.XH00.N4CS, 0xAACD)) { Return (0x02) }
Return (Zero)
}
Method (WO05, 0, Serialized) {
\_SB.PCI0.GPP7.XH00.N4VI = 0x1022
\_SB.PCI0.GPP7.XH00.N4DI = 0x43EF
\_SB.PCI0.GPP7.XH00.N4CI = One
\_SB.PCI0.GPP7.XH00.N4CS = 0xABCD
CNT = Zero
_PTS (0x5)
If (LNotEqual (CNT, 0x5)) { Return (One) }
If (LNotEqual (\_SB.PCI0.GPP7.XH00.N4CS, 0xABCD)) { Return (0x02) }
Return (Zero)
}
}
