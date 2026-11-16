//! Native Rust Integration Test Suite

use std::fs::File;
use std::io::Write;
use tempfile::tempdir;
use zip::write::SimpleFileOptions;
use zip::ZipWriter;

use telegram_dropbox_bot::formatters::{
    extract_ipa_bundle_id, extract_single_file_from_zip, match_app_bundle,
    parse_content_disposition_filename, resolve_dropbox_destination,
};
use telegram_dropbox_bot::github::GitHubService;
use telegram_dropbox_bot::version_checker::{
    format_version_alert_text, format_version_status_text, IosAppInfo,
};

#[test]
fn test_zip_extraction_and_sanitization() {
    let tmp = tempdir().expect("tempdir");
    let zip_path = tmp.path().join("archive.zip");

    // Create a mock zip with macOS metadata, hidden file, and an ipa payload
    let file = File::create(&zip_path).expect("create zip");
    let mut zip = ZipWriter::new(file);

    let options = SimpleFileOptions::default();

    zip.start_file("__MACOSX/._app.ipa", options).expect("file 1");
    zip.write_all(b"macos junk").expect("write 1");

    zip.start_file(".DS_Store", options).expect("file 2");
    zip.write_all(b"ds store").expect("write 2");

    zip.start_file("Payload/DexTube.ipa", options).expect("file 3");
    zip.write_all(b"PK mock ipa binary content").expect("write 3");

    zip.finish().expect("finish");

    let extract_dir = tmp.path().join("extracted");
    std::fs::create_dir_all(&extract_dir).expect("mkdir");

    let res = extract_single_file_from_zip(&zip_path, &extract_dir).expect("extract");
    assert_eq!(res.extracted_name, "DexTube.ipa");
    assert_eq!(res.file_size, 26);
    assert!(res.final_file_path.exists());
}

#[test]
fn test_plist_bundle_extraction() {
    let tmp = tempdir().expect("tempdir");
    let ipa_path = tmp.path().join("mock.ipa");

    // Create a mock IPA with Payload/App.app/Info.plist
    let file = File::create(&ipa_path).expect("create ipa");
    let mut zip = ZipWriter::new(file);
    let options = SimpleFileOptions::default();

    zip.start_file("Payload/YouTube.app/Info.plist", options).expect("file");
    let plist_xml = r#"<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>CFBundleIdentifier</key>
    <string>com.google.ios.youtube</string>
    <key>CFBundleShortVersionString</key>
    <string>20.02.1</string>
</dict>
</plist>"#;
    zip.write_all(plist_xml.as_bytes()).expect("write plist");
    zip.finish().expect("finish ipa");

    let bundle_id = extract_ipa_bundle_id(&ipa_path);
    assert_eq!(bundle_id.as_deref(), Some("com.google.ios.youtube"));
}

#[test]
fn test_app_bundle_rotation_matching() {
    // Exact bundle ID checks
    assert_eq!(
        match_app_bundle("com.google.ios.youtube"),
        Some("com.google.ios.youtube")
    );
    assert_eq!(
        match_app_bundle("com.google.ios.youtubemusic"),
        Some("com.google.ios.youtubemusic")
    );

    // Filename pattern matching
    assert_eq!(
        match_app_bundle("DTKACE_v20.02_plus.ipa"),
        Some("com.google.ios.youtube")
    );
    assert_eq!(
        match_app_bundle("DTLite_v20.01.ipa"),
        Some("com.google.ios.youtube")
    );
    assert_eq!(
        match_app_bundle("YouTube_v20.02.1.ipa"),
        Some("com.google.ios.youtube")
    );
    assert_eq!(
        match_app_bundle("DTMusicUltimate_v7.30.ipa"),
        Some("com.google.ios.youtubemusic")
    );
    assert_eq!(
        match_app_bundle("YouTubeMusic_Lossless.ipa"),
        Some("com.google.ios.youtubemusic")
    );
    assert_eq!(
        match_app_bundle("DexTube_Music_Mod.ipa"),
        Some("com.google.ios.youtubemusic")
    );

    // Unrelated file
    assert_eq!(match_app_bundle("custom_tweak.deb"), None);
}

#[test]
fn test_destination_routing() {
    let (p1, r1, v1) = resolve_dropbox_destination("DTKACE.ipa", "/IPA", "/DEB");
    assert_eq!(p1, "/IPA/DTKACE.ipa");
    assert_eq!(r1, "/IPA");
    assert_eq!(v1, "/IPA");

    let (p2, r2, _v2) = resolve_dropbox_destination("DTMusic.ipa", "/Vault/IPAs", "/Vault/DEBs");
    assert_eq!(p2, "/Vault/IPAs/DTMusic.ipa");
    assert_eq!(r2, "/Vault/IPAs");

    let (p3, r3, v3) = resolve_dropbox_destination("ytkace.deb", "/IPA", "/DEB");
    assert_eq!(p3, "/DEB/ytkace.deb");
    assert_eq!(r3, "/DEB");
    assert_eq!(v3, "/DEB");
}

#[test]
fn test_libsodium_sealedbox_encryption() {
    use base64::prelude::*;
    let key_bytes = [42u8; 32];
    let b64_key = BASE64_STANDARD.encode(&key_bytes);

    let res = GitHubService::encrypt_secret_value(&b64_key, "https://github.com/my/tweak.deb");
    assert!(res.is_ok());
    let enc_b64 = res.unwrap();
    let decoded = BASE64_STANDARD.decode(&enc_b64).expect("valid base64");
    // Libsodium sealed box ciphertext length is payload length (32 bytes) + 48 bytes overhead (ephemeral public key 32B + MAC 16B) = 80 bytes
    assert_eq!(decoded.len(), "https://github.com/my/tweak.deb".len() + 48);
}

#[test]
fn test_content_disposition_parsing() {
    let cd1 = r#"attachment; filename="YouTube_20.02.1.ipa""#;
    assert_eq!(
        parse_content_disposition_filename(cd1).as_deref(),
        Some("YouTube_20.02.1.ipa")
    );

    let cd2 = "attachment; filename*=UTF-8''DexTube%20Plus.ipa";
    assert_eq!(
        parse_content_disposition_filename(cd2).as_deref(),
        Some("DexTube Plus.ipa")
    );
}

#[test]
fn test_version_checker_formatting() {
    let info = IosAppInfo {
        app_key: "youtubemusic".to_string(),
        app_name: "YouTube Music".to_string(),
        bundle_id: "com.google.ios.youtubemusic".to_string(),
        version: "7.32.1".to_string(),
        release_date: "2026-03-24".to_string(),
        release_date_full: "2026-03-24T00:00:00Z".to_string(),
        release_notes: "Enhanced playlist sync".to_string(),
        track_view_url: "https://...".to_string(),
        artwork_url: "https://...".to_string(),
        min_os: "15.0".to_string(),
        icon: "🎵".to_string(),
        target_keys: vec!["dtmusic".to_string()],
    };

    let alert = format_version_alert_text(&info, Some("7.31.0"));
    assert!(alert.contains("NEW IOS VERSION DETECTED!"));
    assert!(alert.contains("com.google.ios.youtubemusic"));
    assert!(alert.contains("`7.32.1`"));
    assert!(alert.contains("`7.31.0`"));

    let overview = format_version_status_text(&[info]);
    assert!(overview.contains("IOS APP STORE VERSION MONITOR"));
    assert!(overview.contains("`DTMUSIC`"));
}
