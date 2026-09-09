import { createContext, useContext } from "react";
export const AttackPilotIdentity = createContext<{ userId: string | null; onLogin: () => void }>({ userId: null, onLogin: () => {} });
export const useAttackPilotIdentity = () => useContext(AttackPilotIdentity);
