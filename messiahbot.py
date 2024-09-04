import os
import discord
from discord.ext import commands, tasks
from discord import File
import asyncio
from langchain_groq import ChatGroq
from langchain_core.prompts import PromptTemplate
from langchain_core.output_parsers import StrOutputParser
from youtube_transcript_api import YouTubeTranscriptApi
from googleapiclient.discovery import build
from dotenv import load_dotenv
import requests
import nest_asyncio

# Load the .env file
load_dotenv(r"E:\project_data\discordbot.env")

# Set up API keys
os.environ['LANGCHAIN_API_KEY'] = os.getenv('LANGCHAIN_API_KEY')
os.environ['GROQ_API_KEY'] = os.getenv('GROQ_API_KEY')
os.environ['YOUTUBE_API_KEY'] = os.getenv('YOUTUBE_API_KEY')
BOT_TOKEN = os.getenv('BOT_TOKEN')

llm = ChatGroq(model="llama3-8b-8192")

class YouTubeSummarizer:
    def __init__(self, custom_url, discord_channel_name):
        self.custom_url = custom_url
        self.discord_channel_name = discord_channel_name
        self.youtube = build('youtube', 'v3', developerKey=os.environ['YOUTUBE_API_KEY'])
        self.llm = llm
        self.transcript_summary_prompt = PromptTemplate(
            input_variables=["transcript"],
            template="""
            Summarize the following transcript into concise bullet points:

            {transcript}

            Summary:
            -
            """
        )

    def get_channel_id_from_custom_url(self):
        request = self.youtube.search().list(
            part='snippet',
            q=self.custom_url,
            type='channel'
        )
        response = request.execute()
        channel_id = response['items'][0]['snippet']['channelId']
        return channel_id

    def get_latest_video_id(self, channel_id):
        request = self.youtube.search().list(
            part='snippet',
            channelId=channel_id,
            maxResults=1,
            order='date'
        )
        response = request.execute()
        latest_video_id = response['items'][0]['id']['videoId']
        return latest_video_id

    def fetch_transcript(self, video_id):
        transcript = YouTubeTranscriptApi.get_transcript(video_id)
        full_transcript = " ".join([entry['text'] for entry in transcript])
        return full_transcript

    async def summarize_transcript(self, transcript):
        summary = self.transcript_summary_prompt | self.llm | StrOutputParser()
        summary_text = summary.invoke({"transcript": transcript})
        return summary_text

    async def post_summary_to_discord(self, summary, bot):
        for guild in bot.guilds:
            for channel in guild.text_channels:
                if channel.name == self.discord_channel_name:
                    await channel.send(summary)
                    break

    async def summarize_latest_video(self, bot):
        channel_id = self.get_channel_id_from_custom_url()
        latest_video_id = self.get_latest_video_id(channel_id)
        transcript = self.fetch_transcript(latest_video_id)
        summary = await self.summarize_transcript(transcript)
        await self.post_summary_to_discord(summary, bot)

    @tasks.loop(hours=3)
    async def periodic_summarization(self, bot):
        await self.summarize_latest_video(bot)

class ModerationChain:
    def __init__(self):
        self.llm = ChatGroq(model="llama3-8b-8192")

    def process(self, message_content: str) -> bool:
        goat_prompt = PromptTemplate(
            input_variables=["message_content"],
            template="""
            You are an avid Lionel Messi and FC Barcelona fan. Analyze the following message and determine the tone of the message.
            If the tone of the message includes criticism, vulgarity, racial slurs, or mockery towards Lionel Messi or FC Barcelona,
            return "1". Otherwise, return "0". If the context of the message is unclear or inconclusive, return "0".
            If the message is too short to understand the context, return "0". If the message is not in English, return "0".

            Message: {message_content}

            Your output should be in the following format:
            0 or 1

            VERY IMPORTANT: This format should be strictly followed. No other text or explanation is allowed.
            """
        )

        parser = StrOutputParser()
        chain = goat_prompt | self.llm | parser

        answer = chain.invoke({"message_content": message_content})

        # Ensure the output is either "0" or "1"
        try:
            result = int(answer.strip())
            if result not in [0, 1]:
                raise ValueError("Output not 0 or 1")
        except ValueError:
            result = int(0)  # Default to not deleting the message if the output is unexpected

        return answer

# Discord bot setup
intents = discord.Intents.default()
intents.messages = True
intents.message_content = True

bot = commands.Bot(command_prefix='!', intents=intents)

quote_prompt = PromptTemplate(
    template="""
    Give a real quote about Lionel Messi, said by football legends. Make sure that the quote is in English and is not fake.

    Your output should be in the following format:
    'They tell me that all men are equal in God’s eyes, this player makes you seriously think about those words.' - soccer commentator Ray Hudson 

    Don't deviate from this format and DON NOT give the same quotes DO NOT write "Here is a  quote about Lionel Messi and FC Barcelona , said by football legends:" or anything else at the beginning.
    """
)

youtube_summarizer = YouTubeSummarizer(custom_url="FabrizioRomanoYT", discord_channel_name="football-messiah")

@bot.event
async def on_ready():
    print(f'Logged in as {bot.user}')

    image_url = "https://fifpro.org/media/fhmfhvkx/messi-world-cup.jpg?rxy=0.48356841796117644,0.31512414378031967&width=1000&height=640&rnd=133210253587130000"
    quote = quote_prompt | llm | StrOutputParser()

    quote_text = quote.invoke({})
    embed = discord.Embed(description=quote_text)
    embed.set_image(url=image_url)

    # Send the embed to the 'general' channel
    for guild in bot.guilds:
        for channel in guild.text_channels:
            if channel.name == 'general':
                await channel.send(embed=embed)
                break


@bot.event
async def on_ready():
    print(f'Logged in as {bot.user}')

    # Send the embed to the 'general' channel
    for guild in bot.guilds:
        for channel in guild.text_channels:
            if channel.name == 'football-messiah':
                await youtube_summarizer.summarize_latest_video(bot)
                youtube_summarizer.periodic_summarization.start(bot)
                break

mod = ModerationChain()

@bot.command()
async def delete(ctx, message_id: int):
    try:
        message = await ctx.channel.fetch_message(message_id)
        await message.delete()
        await ctx.send(f'Message {message_id} deleted.')
    except discord.NotFound:
        await ctx.send(f'Message {message_id} not found.')
    except discord.Forbidden:
        await ctx.send('I do not have permission to delete messages.')
    except discord.HTTPException as e:
        await ctx.send(f'Failed to delete message: {e}')

@bot.event
async def on_message(message):
    if message.author == bot.user:
        return

    if isinstance(message.channel, discord.DMChannel):
        return  # Ignore messages from DMs

    # Use the LangChain chain to decide whether to delete the message
    should_delete = mod.process(message.content)

    if should_delete == '1':
        await message.delete()
        await message.channel.send(f'Message deleted because Messi is the GOAT and FC Barcelona is more than just a club, VISCA EL BARCA.')

        # Send the Messi image and quote
        image_url = "https://fifpro.org/media/fhmfhvkx/messi-world-cup.jpg?rxy=0.48356841796117644,0.31512414378031967&width=1000&height=640&rnd=133210253587130000"
        quote = quote_prompt | llm | StrOutputParser()
        quote_text = quote.invoke({})
        embed = discord.Embed(description=quote_text)
        embed.set_image(url=image_url)
        await message.channel.send(embed=embed)

    await bot.process_commands(message)

@bot.command()
async def transfer_news(ctx):
    await youtube_summarizer.summarize_latest_video(bot)



nest_asyncio.apply()

if __name__ == "__main__":
    bot.run(BOT_TOKEN)
else:
    async def run_bot():
        await bot.start(BOT_TOKEN)

    loop = asyncio.get_event_loop()
    loop.create_task(run_bot())
    loop.run_forever()
