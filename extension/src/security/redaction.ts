import { ContractNotImplementedError } from "../errors.js";

declare const persistableSanitizedObservationBrand: unique symbol;
declare const validatedRawObservationBrand: unique symbol;

type ValidatedRawObservationV1 = Readonly<{
  readonly [validatedRawObservationBrand]: "RawObservation";
  readonly canonicalBytes: Uint8Array;
}>;

export type PersistableSanitizedObservationV1 = Readonly<{
  readonly [persistableSanitizedObservationBrand]: never;
  readonly canonicalSanitizedBytes: Uint8Array;
  readonly validatedRawObservation: ValidatedRawObservationV1;
}>;

export const projectBeforePersistence = (
  input: unknown,
): PersistableSanitizedObservationV1 => {
  String(input);
  throw new ContractNotImplementedError("SEC0-T06");
};
