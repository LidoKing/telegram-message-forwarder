from telethon import TelegramClient, events, sync, utils
from telethon.tl.types import InputChannel, MessageEntityTextUrl, MessageEntityBold, MessageEntityUnderline, MessageMediaPhoto

import lark_oapi as lark
from lark_oapi.api.im.v1 import *
from lark_oapi.api.auth.v3 import *

import json
import yaml
import logging
import requests
from requests_toolbelt import MultipartEncoder

''' 
------------------------------------------------------------------------
                LOGGING - Initite logging for the Bot
------------------------------------------------------------------------
'''
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logging.getLogger('telethon').setLevel(level=logging.WARNING)
logger = logging.getLogger(__name__)

''' 
------------------------------------------------------------------------
    BOT FUNCTION - Everything that happens, happens for a reason
------------------------------------------------------------------------
'''

# Get config file
with open('config.yaml', 'rb') as f:
    config = yaml.safe_load(f)

# Construct lark client
larkClient = lark.Client.builder() \
    .app_id(config["lark_app_id"]) \
    .app_secret(config["lark_app_secret"]) \
    .domain("https://open.larksuite.com") \
    .build()

def getTenantToken() :
    # 构造请求对象
    request: InternalTenantAccessTokenRequest = InternalTenantAccessTokenRequest.builder() \
        .request_body(InternalTenantAccessTokenRequestBody.builder()
                      .app_id(config["lark_app_id"])
                      .app_secret(config["lark_app_secret"])
                      .build()) \
        .build()

    # 发起请求
    response: InternalTenantAccessTokenResponse = larkClient.auth.v3.tenant_access_token.internal(request)

    # 处理失败返回
    if not response.success():
        lark.logger.error(
            f"client.auth.v3.tenant_access_token.internal failed, code: {response.code}, msg: {response.msg}, log_id: {response.get_log_id()}")
        return

    # 处理业务结果
    print(response.raw.content)

# Send msg to Lark group
def sendMsg(msg):
    # Construct request
    request: CreateMessageRequest = CreateMessageRequest.builder() \
        .receive_id_type("chat_id") \
        .request_body(CreateMessageRequestBody.builder()
                      .receive_id("oc_b22069cc62e369fe43c07d9a2ca5ebea") # oc_e81e3be03b3bdb0251d0d6127eb1e5f9
                      .msg_type("post")
                      .content(msg)
                      .build()) \
        .build()

    # Send request
    response: CreateMessageResponse = larkClient.im.v1.message.create(request)

    # Handle error
    if not response.success():
        lark.logger.error(
            f"client.im.v1.message.create failed, code: {response.code}, msg: {response.msg}, log_id: {response.get_log_id()}")
        return

# Upload img to Lark server
def uploadImage(photoInBytes):
    url = "https://open.larksuite.com/open-apis/im/v1/images"

    form = {
        'image_type': 'message',
        'image': ('image.jpg', photoInBytes, 'image/jpeg')
    } 
    multi_form = MultipartEncoder(form)

    headers = {
        'Authorization': f'Bearer {config["lark_tenant"]}',
        'Content-Type': multi_form.content_type
    }

    response = requests.request("POST", url, headers=headers, data=multi_form)
    raw = json.loads(response.content.decode('utf-8'))
    image_key = raw['data']['image_key']
    print(f"Uploaded image for message with key {image_key}")

    return image_key

def start():
    # Telegram Client Init
    client = TelegramClient(config["session_name"], 
                            config["api_id"], 
                            config["api_hash"])
    # Telegram Client Start
    client.start()

    print("Telegram client craeted");

    # Input Messages Telegram Channels will be stored in these empty Entities
    input_channels_entities = []
    output_channel_entities = [0]

    # Iterating over dialogs and finding new entities and pushing them to our empty entities list above
    for d in client.iter_dialogs():
        if d.name in config["input_channel_names"] or d.entity.id in config["input_channel_ids"]:
            input_channels_entities.append(InputChannel(d.entity.id, d.entity.access_hash))
        # if d.name in config["output_channel_names"] or d.entity.id in config["output_channel_ids"]:
        #     output_channel_entities.append(InputChannel(d.entity.id, d.entity.access_hash))

    # Exit, dont wait for fire.        
    # if not output_channel_entities:
    #     logger.error(f"Could not find any output channels in the user's dialogs")
    #     sys.exit(1)

    if not input_channels_entities:
        logger.error(f"Could not find any input channels in the user's dialogs")
        sys.exit(1)
    
    # Use logging and print messages on your console.     
    logging.info(f"Listening on {len(input_channels_entities)} channels. Forwarding messages to {len(output_channel_entities)} channels.")
    

    # TELEGRAM NEW MESSAGE - When new message triggers, come here

    print("Polling...");

    @client.on(events.NewMessage(chats=input_channels_entities))
    async def handler(event):
        for output_channel in output_channel_entities:
            print("\n Message received \n")
            msg = event.message.message
            entities = event.message.entities
            media = event.message.media
            formatted_msg = { "en_us": { "content": [[]] } }
            content = formatted_msg["en_us"]["content"][0]

            if media:
                if type(media) is MessageMediaPhoto:
                    # Get the photo as binary data
                    photo = await event.message.download_media(file=bytes)
                    # Upload image to Lark so that it can be sent
                    image_key = uploadImage(photo)
                    content.append({ "tag": "img", "image_key": image_key })

            if entities:
                # Get all words with entity (e.g. bold, link, underline...)
                words_with_entity = utils.get_inner_text(msg, entities)

                for index, word in enumerate(words_with_entity):
                    # Get correct offset, offset provided by Telegram is not accurate
                    offset = msg.find(word)
                    length = len(word)
                    end = offset + length

                    entity_type = type(entities[index])
                    # Use text urls as a separator
                    # everything before a text url is normal text
                    if entity_type is MessageEntityTextUrl:
                        content.append({ "tag": "text", "text": msg[:offset] })
                        content.append({ "tag": "a", "href": entities[index].url, "text": msg[offset:end] })
                        msg = msg[end:]

                    # Append remaining msg as normal text if it is last entity
                    if index == len(words_with_entity) - 1: 
                        content.append({ "tag": "text", "text": msg })
            else:
                # If there are photo captions, and not just an image was sent
                if msg:
                    content.append({ "tag": "text", "text": msg })

            # this will forward your message to lark
            sendMsg(json.dumps(formatted_msg))

    client.run_until_disconnected()

''' 
------------------------------------------------------------------------
          MAIN FUNCTION - Can't dream without a brain ...
------------------------------------------------------------------------
'''

if __name__ == "__main__":
    start()
