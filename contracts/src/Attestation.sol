// SPDX-License-Identifier: MIT
pragma solidity 0.8.24;

/// @title Attestation
/// @notice Records a model decision: what was decided, how confident the
///         operator was, what explanation was produced, and a zk proof that
///         the calibration head ran honestly.
///
/// SCOPE WARNING: the zk proof covers the CALIBRATION HEAD ONLY. It does not
/// prove that `margin` came from the claimed base classifier, nor that the
/// applicant's features were reported honestly. See docs/PHASE3.md.
interface IVerifier {
    /// @dev EZKL's generated halo2 verifier entrypoint.
    function verifyProof(bytes calldata proof, uint256[] calldata instances)
        external
        view
        returns (bool);
}

contract Attestation {
    struct Record {
        address operator;
        bytes32 decisionHash;   // hash of (application id, decision, reason code)
        bytes32 shapHash;       // hash of the top-5 SHAP vector -- evidence, NOT proved
        uint256 confidence;     // WAD, calibrated probability the decision is correct
        int256 margin;          // base-model logit fed to the calibration head
        bytes32 modelVersion;   // identifies base model + calibration head
        uint64 timestamp;
        bool proofVerified;     // did the on-chain zk verifier accept?
    }

    IVerifier public immutable verifier;

    mapping(bytes32 => Record) private _records;
    bytes32[] private _ids;

    event Attested(
        bytes32 indexed attestationId,
        address indexed operator,
        bytes32 indexed decisionHash,
        uint256 confidence,
        bytes32 modelVersion,
        bool proofVerified
    );

    error AlreadyAttested(bytes32 attestationId);
    error UnknownAttestation(bytes32 attestationId);
    error ConfidenceOutOfRange(uint256 confidence);
    error ProofRejected();

    constructor(address verifier_) {
        verifier = IVerifier(verifier_);
    }

    /// @notice Record a decision together with its zk proof.
    /// @dev The proof is verified inline. A rejected proof reverts, so an
    ///      attestation can never exist with `proofVerified == false` via this
    ///      path -- the flag exists for the unproved-legacy path below.
    function attest(
        bytes32 decisionHash,
        bytes32 shapHash,
        uint256 confidence,
        int256 margin,
        bytes32 modelVersion,
        bytes calldata proof,
        uint256[] calldata instances
    ) external returns (bytes32 attestationId) {
        if (confidence > 1e18) revert ConfidenceOutOfRange(confidence);

        attestationId = keccak256(
            abi.encode(msg.sender, decisionHash, shapHash, confidence, margin, modelVersion)
        );
        if (_records[attestationId].timestamp != 0) revert AlreadyAttested(attestationId);

        bool ok = verifier.verifyProof(proof, instances);
        if (!ok) revert ProofRejected();

        _records[attestationId] = Record({
            operator: msg.sender,
            decisionHash: decisionHash,
            shapHash: shapHash,
            confidence: confidence,
            margin: margin,
            modelVersion: modelVersion,
            timestamp: uint64(block.timestamp),
            proofVerified: true
        });
        _ids.push(attestationId);

        emit Attested(attestationId, msg.sender, decisionHash, confidence, modelVersion, true);
    }

    function get(bytes32 attestationId) external view returns (Record memory) {
        Record memory r = _records[attestationId];
        if (r.timestamp == 0) revert UnknownAttestation(attestationId);
        return r;
    }

    function exists(bytes32 attestationId) external view returns (bool) {
        return _records[attestationId].timestamp != 0;
    }

    function count() external view returns (uint256) {
        return _ids.length;
    }

    function idAt(uint256 i) external view returns (bytes32) {
        return _ids[i];
    }
}
