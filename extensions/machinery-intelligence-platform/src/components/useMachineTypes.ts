"use client";

import { useEffect, useState } from "react";

export interface MachineType {
  id: string;
  name: string;
}

/** Fetches the fixed machine-type taxonomy for form dropdowns. */
export function useMachineTypes() {
  const [machineTypes, setMachineTypes] = useState<MachineType[]>([]);

  useEffect(() => {
    let cancelled = false;
    fetch("/api/machine-types")
      .then((res) => res.json())
      .then((body) => {
        if (!cancelled) setMachineTypes(body.machineTypes ?? []);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  return machineTypes;
}
