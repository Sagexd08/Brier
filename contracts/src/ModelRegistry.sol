// SPDX-License-Identifier: MIT
pragma solidity 0.8.24;

/// @title Content-addressed registry of model / calibration-head versions.
///
/// MOTIVATION. A halo2 verifying key covers a *program*, not an *input*: one
/// vkey verifies every proof produced by that circuit, whatever weights were
/// baked into it at compile time. So `model_version` cannot be inferred from
/// the proof -- it has to be an explicit public commitment, or an attestation
/// silently means "some version of this head ran" rather than "this one did".
///
/// WHAT THIS GUARANTEES, precisely: that the artifact referenced by a version
/// id hashes to the value recorded here. Anyone can fetch the artifact from
/// the recorded URI, hash it, and detect substitution. That is content
/// integrity, and it is genuinely useful.
///
/// WHAT IT DOES NOT GUARANTEE, and must never be described as guaranteeing:
///
///   * that the training process was honest. Nothing here says the data was
///     unpoisoned, the split was clean, or the reported metrics were produced
///     by the artifact being registered. A registrant can honestly register a
///     dishonestly trained model.
///   * that the registered artifact is the one the operator actually ran. The
///     attestation references a version id; the proof does not bind the id to
///     the circuit. This is the same input-provenance gap the margin has.
///   * that the URI will resolve. Content addressing detects substitution; it
///     does not prevent the bytes disappearing.
///
/// Training integrity is a different and much harder problem, and it is out of
/// scope here. The registry closes a naming gap, not a trust gap.
contract ModelRegistry {
    struct Version {
        bytes32 artifactHash;   // keccak256 of the canonical artifact bundle
        bytes32 datasetHash;    // hash of the dataset/split descriptor
        address registrant;
        uint64 registeredAt;
        string uri;             // ipfs://... or ar://...
    }

    /// @notice Version id -> record. The id is chosen by the registrant and is
    ///         what an attestation carries as `model_version`.
    mapping(bytes32 => Version) internal _versions;

    /// @notice Reverse index: artifact hash -> version id that claimed it.
    /// @dev Lets a verifier go from bytes they hold to the id, so a
    ///      substituted artifact is detectable from either direction.
    mapping(bytes32 => bytes32) public versionForArtifact;

    address public immutable admin;

    event VersionRegistered(
        bytes32 indexed versionId,
        bytes32 indexed artifactHash,
        bytes32 datasetHash,
        address indexed registrant,
        string uri
    );
    event VersionRevoked(bytes32 indexed versionId, string reason);

    mapping(bytes32 => string) public revocationReason;
    mapping(bytes32 => bool) public isRevoked;

    error NotAdmin();
    error VersionExists(bytes32 versionId);
    error UnknownVersion(bytes32 versionId);
    error ZeroArtifactHash();
    error EmptyUri();
    error AlreadyRevoked(bytes32 versionId);

    constructor(address admin_) {
        admin = admin_;
    }

    /// @notice Register a new version. Ids are immutable once claimed.
    /// @dev Deliberately permissionless to *register* -- anyone may publish a
    ///      version of their own model, and the id namespace is content-derived
    ///      in practice. What matters is that an id, once taken, can never be
    ///      repointed at different bytes: that is the whole guarantee, and a
    ///      mutable mapping would destroy it.
    function register(
        bytes32 versionId,
        bytes32 artifactHash,
        bytes32 datasetHash,
        string calldata uri
    ) external {
        if (_versions[versionId].artifactHash != bytes32(0)) revert VersionExists(versionId);
        if (artifactHash == bytes32(0)) revert ZeroArtifactHash();
        if (bytes(uri).length == 0) revert EmptyUri();

        _versions[versionId] = Version({
            artifactHash: artifactHash,
            datasetHash: datasetHash,
            registrant: msg.sender,
            registeredAt: uint64(block.timestamp),
            uri: uri
        });
        // First claim wins. A second version registering identical bytes does
        // not overwrite the index, so the original attribution survives.
        if (versionForArtifact[artifactHash] == bytes32(0)) {
            versionForArtifact[artifactHash] = versionId;
        }

        emit VersionRegistered(versionId, artifactHash, datasetHash, msg.sender, uri);
    }

    /// @notice Check bytes against a registered version.
    /// @param versionId The claimed version.
    /// @param candidateHash keccak256 of the artifact the verifier actually holds.
    /// @return True only if the version exists and the hashes match exactly.
    /// @dev This is the function the whole contract exists for. A tampered
    ///      artifact -- different weights, same claimed version -- returns false.
    function verifyArtifact(bytes32 versionId, bytes32 candidateHash)
        external
        view
        returns (bool)
    {
        bytes32 known = _versions[versionId].artifactHash;
        return known != bytes32(0) && known == candidateHash;
    }

    function get(bytes32 versionId) external view returns (Version memory) {
        Version memory v = _versions[versionId];
        if (v.artifactHash == bytes32(0)) revert UnknownVersion(versionId);
        return v;
    }

    function exists(bytes32 versionId) external view returns (bool) {
        return _versions[versionId].artifactHash != bytes32(0);
    }

    /// @notice Flag a version as withdrawn. The record itself is NOT deleted.
    /// @dev Revocation is advisory metadata: it says "do not use this", not
    ///      "this never existed". Deleting the record would break verification
    ///      of historical attestations that legitimately referenced it, which
    ///      is exactly the audit trail the registry is supposed to protect.
    function revoke(bytes32 versionId, string calldata reason) external {
        if (msg.sender != admin) revert NotAdmin();
        if (_versions[versionId].artifactHash == bytes32(0)) revert UnknownVersion(versionId);
        if (isRevoked[versionId]) revert AlreadyRevoked(versionId);
        isRevoked[versionId] = true;
        revocationReason[versionId] = reason;
        emit VersionRevoked(versionId, reason);
    }
}
