export interface CapabilitiesResponseWire {
  families?: CapabilityFamilyWire[];
}

export interface CapabilityFamilyWire {
  id: string;
  label: string;
  capabilities?: CapabilityItemWire[];
}

export interface CapabilityItemWire {
  id: string;
  description: string;
  tool_names?: string[];
  cognitive?: boolean;
}
