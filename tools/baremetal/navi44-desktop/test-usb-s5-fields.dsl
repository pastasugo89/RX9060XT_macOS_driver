/* Load AFTER the production SSDT in the ACPICA simulator. */
DefinitionBlock ("", "SSDT", 2, "NAVI44", "S5FIELDS", 1)
{
External (\_SB.PCI0.GPP7.XH00, DeviceObj)
External (\_SB.PCI0.GPP7.XH00.N4CF, OpRegionObj)
Scope (\_SB.PCI0.GPP7.XH00) { Field (N4CF, ByteAcc, NoLock, Preserve) { Offset (0x7C), N4CS, 16 } }
External (\_SB.PCI0.GP17.XHC0, DeviceObj)
External (\_SB.PCI0.GP17.XHC0.N4CF, OpRegionObj)
Scope (\_SB.PCI0.GP17.XHC0) { Field (N4CF, ByteAcc, NoLock, Preserve) { Offset (0x54), N4CS, 16 } }
External (\_SB.PCI0.GP17.XHC1, DeviceObj)
External (\_SB.PCI0.GP17.XHC1.N4CF, OpRegionObj)
Scope (\_SB.PCI0.GP17.XHC1) { Field (N4CF, ByteAcc, NoLock, Preserve) { Offset (0x54), N4CS, 16 } }
External (\_SB.PCI0.GP19.XHC2, DeviceObj)
External (\_SB.PCI0.GP19.XHC2.N4CF, OpRegionObj)
Scope (\_SB.PCI0.GP19.XHC2) { Field (N4CF, ByteAcc, NoLock, Preserve) { Offset (0x54), N4CS, 16 } }
}
