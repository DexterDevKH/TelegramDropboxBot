//! Telegram Bot API Client & Native Bot API v7.0+ Integration

use std::fs::File;
use std::io::Write;
use std::path::Path;

use futures_util::StreamExt;
use serde::Deserialize;

use crate::formatters::normalize_url;

#[derive(Debug, Clone, Deserialize)]
pub struct TelegramUser {
    pub id: i64,
    pub is_bot: bool,
    pub first_name: String,
    pub username: Option<String>,
}

#[derive(Debug, Clone, Deserialize)]
pub struct TelegramChat {
    pub id: i64,
    #[serde(rename = "type")]
    pub chat_type: String,
    pub title: Option<String>,
    pub username: Option<String>,
}

#[derive(Debug, Clone, Deserialize)]
pub struct TelegramDocument {
    pub file_id: String,
    pub file_unique_id: String,
    pub file_name: Option<String>,
    pub mime_type: Option<String>,
    pub file_size: Option<u64>,
}

#[derive(Debug, Clone, Deserialize)]
pub struct TelegramPhotoSize {
    pub file_id: String,
    pub file_size: Option<u64>,
}

#[derive(Debug, Clone, Deserialize)]
pub struct TelegramVideo {
    pub file_id: String,
    pub file_unique_id: String,
    pub file_name: Option<String>,
    pub mime_type: Option<String>,
    pub file_size: Option<u64>,
}

#[derive(Debug, Clone, Deserialize)]
pub struct TelegramAudio {
    pub file_id: String,
    pub file_unique_id: String,
    pub file_name: Option<String>,
    pub mime_type: Option<String>,
    pub file_size: Option<u64>,
}

#[derive(Debug, Clone, Deserialize)]
pub struct TelegramMessage {
    pub message_id: i64,
    pub from: Option<TelegramUser>,
    pub chat: TelegramChat,
    pub date: i64,
    pub text: Option<String>,
    pub caption: Option<String>,
    pub document: Option<TelegramDocument>,
    pub photo: Option<Vec<TelegramPhotoSize>>,
    pub video: Option<TelegramVideo>,
    pub audio: Option<TelegramAudio>,
}

#[derive(Debug, Clone, Deserialize)]
pub struct TelegramCallbackQuery {
    pub id: String,
    pub from: TelegramUser,
    pub message: Option<TelegramMessage>,
    pub data: Option<String>,
}

#[derive(Debug, Clone, Deserialize)]
pub struct TelegramUpdate {
    pub update_id: i64,
    pub message: Option<TelegramMessage>,
    pub callback_query: Option<TelegramCallbackQuery>,
}

#[derive(Debug, Clone, Deserialize)]
struct TelegramResponse<T> {
    pub ok: bool,
    pub result: Option<T>,
    pub description: Option<String>,
}

#[derive(Debug, Clone, Deserialize)]
#[allow(dead_code)]
struct TelegramFileResult {
    pub file_id: String,
    pub file_path: Option<String>,
    pub file_size: Option<u64>,
}

pub struct TelegramService {
    bot_token: String,
    client: reqwest::Client,
    pub bot_username: String,
}

impl TelegramService {
    pub fn new(bot_token: String) -> Self {
        let client = reqwest::Client::builder()
            .timeout(std::time::Duration::from_secs(35))
            .build()
            .unwrap_or_default();

        Self {
            bot_token,
            client,
            bot_username: "UnknownBot".to_string(),
        }
    }

    pub async fn get_me(&mut self) -> Result<String, String> {
        let url = format!("https://api.telegram.org/bot{}/getMe", self.bot_token);
        let resp = self
            .client
            .get(&url)
            .send()
            .await
            .map_err(|e| format!("getMe HTTP failed: {}", e))?;

        if !resp.status().is_success() {
            return Err(format!("getMe error: HTTP {}", resp.status()));
        }

        let body: TelegramResponse<TelegramUser> = resp
            .json()
            .await
            .map_err(|e| format!("getMe JSON parse error: {}", e))?;

        if let Some(user) = body.result {
            let uname = user.username.unwrap_or(user.first_name);
            self.bot_username = uname.clone();
            Ok(uname)
        } else {
            Err(body
                .description
                .unwrap_or_else(|| "getMe failed".to_string()))
        }
    }

    pub async fn send_message(
        &self,
        chat_id: i64,
        text: &str,
        reply_to_message_id: Option<i64>,
        reply_markup: Option<serde_json::Value>,
    ) -> Result<i64, String> {
        let url = format!("https://api.telegram.org/bot{}/sendMessage", self.bot_token);
        let mut payload = serde_json::json!({
            "chat_id": chat_id,
            "text": text,
            "parse_mode": "Markdown",
            "disable_web_page_preview": true,
        });

        if let Some(reply_id) = reply_to_message_id {
            payload["reply_to_message_id"] = serde_json::json!(reply_id);
        }
        if let Some(markup) = reply_markup {
            payload["reply_markup"] = markup;
        }

        let resp = self
            .client
            .post(&url)
            .json(&payload)
            .send()
            .await
            .map_err(|e| format!("sendMessage error: {}", e))?;

        let body: TelegramResponse<TelegramMessage> = resp
            .json()
            .await
            .map_err(|e| format!("sendMessage JSON error: {}", e))?;

        if let Some(msg) = body.result {
            Ok(msg.message_id)
        } else {
            Err(body
                .description
                .unwrap_or_else(|| "Failed to send message".to_string()))
        }
    }

    pub async fn edit_message_text(
        &self,
        chat_id: i64,
        message_id: i64,
        text: &str,
        reply_markup: Option<serde_json::Value>,
    ) -> Result<(), String> {
        let url = format!(
            "https://api.telegram.org/bot{}/editMessageText",
            self.bot_token
        );
        let mut payload = serde_json::json!({
            "chat_id": chat_id,
            "message_id": message_id,
            "text": text,
            "parse_mode": "Markdown",
            "disable_web_page_preview": true,
        });

        if let Some(markup) = reply_markup {
            payload["reply_markup"] = markup;
        }

        let resp = self
            .client
            .post(&url)
            .json(&payload)
            .send()
            .await
            .map_err(|e| format!("editMessageText error: {}", e))?;

        let body: TelegramResponse<serde_json::Value> = resp
            .json()
            .await
            .map_err(|e| format!("editMessageText parse error: {}", e))?;

        if body.ok {
            Ok(())
        } else {
            let desc = body.description.unwrap_or_default();
            if desc.contains("message is not modified") {
                Ok(())
            } else {
                Err(desc)
            }
        }
    }

    /// Applies official client-side CopyTextButton via HTTP Bot API (v7.0+).
    /// Writes direct download link (dl=1) straight to OS clipboard on a single tap.
    pub async fn apply_native_copy_button(
        &self,
        chat_id: i64,
        message_id: i64,
        shared_url: &str,
    ) -> Result<bool, String> {
        let web_url = shared_url;
        let direct_url = normalize_url(shared_url);

        let url = format!(
            "https://api.telegram.org/bot{}/editMessageReplyMarkup",
            self.bot_token
        );
        let payload = serde_json::json!({
            "chat_id": chat_id,
            "message_id": message_id,
            "reply_markup": {
                "inline_keyboard": [
                    [
                        {
                            "text": "📋 Copy Direct Link",
                            "copy_text": { "text": direct_url }
                        },
                        {
                            "text": "🌐 Open in Dropbox",
                            "url": web_url
                        }
                    ]
                ]
            }
        });

        let resp = self
            .client
            .post(&url)
            .json(&payload)
            .send()
            .await
            .map_err(|e| format!("apply_native_copy_button error: {}", e))?;

        if !resp.status().is_success() {
            // Fallback for environments where copy_text is unsupported
            let fallback_payload = serde_json::json!({
                "chat_id": chat_id,
                "message_id": message_id,
                "reply_markup": {
                    "inline_keyboard": [
                        [
                            {
                                "text": "🌐 Open in Dropbox",
                                "url": web_url
                            }
                        ]
                    ]
                }
            });
            let _ = self.client.post(&url).json(&fallback_payload).send().await;
        }

        Ok(resp.status().is_success())
    }

    pub async fn answer_callback_query(
        &self,
        callback_query_id: &str,
        text: Option<&str>,
    ) -> Result<(), String> {
        let url = format!(
            "https://api.telegram.org/bot{}/answerCallbackQuery",
            self.bot_token
        );
        let mut payload = serde_json::json!({ "callback_query_id": callback_query_id });
        if let Some(t) = text {
            payload["text"] = serde_json::json!(t);
        }

        let _ = self.client.post(&url).json(&payload).send().await;
        Ok(())
    }

    pub async fn get_updates(
        &self,
        offset: i64,
        timeout_secs: u64,
    ) -> Result<Vec<TelegramUpdate>, String> {
        let url = format!("https://api.telegram.org/bot{}/getUpdates", self.bot_token);
        let payload = serde_json::json!({
            "offset": offset,
            "timeout": timeout_secs,
            "allowed_updates": ["message", "callback_query"],
        });

        let resp = self
            .client
            .post(&url)
            .json(&payload)
            .send()
            .await
            .map_err(|e| format!("getUpdates HTTP error: {}", e))?;

        let body: TelegramResponse<Vec<TelegramUpdate>> = resp
            .json()
            .await
            .map_err(|e| format!("getUpdates parse error: {}", e))?;

        Ok(body.result.unwrap_or_default())
    }

    pub async fn download_file_by_id<F>(
        &self,
        file_id: &str,
        dest_path: &Path,
        mut progress_cb: F,
    ) -> Result<u64, String>
    where
        F: FnMut(u64, u64),
    {
        let url = format!(
            "https://api.telegram.org/bot{}/getFile?file_id={}",
            self.bot_token, file_id
        );
        let resp = self
            .client
            .get(&url)
            .send()
            .await
            .map_err(|e| format!("getFile error: {}", e))?;

        let body: TelegramResponse<TelegramFileResult> = resp
            .json()
            .await
            .map_err(|e| format!("getFile parse error: {}", e))?;

        let file_info = body
            .result
            .ok_or_else(|| "Missing file result in getFile".to_string())?;
        let file_path = file_info
            .file_path
            .ok_or_else(|| "Missing file_path in getFile".to_string())?;

        let dl_url = format!(
            "https://api.telegram.org/file/bot{}/{}",
            self.bot_token, file_path
        );

        let dl_resp = self
            .client
            .get(&dl_url)
            .send()
            .await
            .map_err(|e| format!("Download stream error: {}", e))?;

        let total_bytes = dl_resp.content_length().unwrap_or(0);
        let mut downloaded: u64 = 0;
        let mut file =
            File::create(dest_path).map_err(|e| format!("File creation failed: {}", e))?;

        let mut stream = dl_resp.bytes_stream();
        while let Some(chunk_res) = stream.next().await {
            let chunk = chunk_res.map_err(|e| format!("Stream read error: {}", e))?;
            file.write_all(&chunk)
                .map_err(|e| format!("File write error: {}", e))?;
            downloaded += chunk.len() as u64;
            progress_cb(downloaded, total_bytes);
        }

        Ok(downloaded)
    }
}
