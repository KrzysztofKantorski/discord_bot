import os
import discord
from discord import app_commands
from discord.ui import Button, View
from aiohttp import web, BasicAuth
import aiohttp
import asyncio



TOKEN = os.getenv("DISCORD_TOKEN")
JENKINS_URL = os.getenv("JENKINS_URL") 
JENKINS_USER = os.getenv("JENKINS_USER")
JENKINS_TOKEN = os.getenv("JENKINS_TOKEN")
CHANNEL_ID = int(os.getenv("DISCORD_CHANNEL_ID"))
JOB_NAME = os.getenv("JENKINS_JOB_NAME", "Github-Project")

class MyBot(discord.Client):
    def __init__(self):
        super().__init__(intents=discord.Intents.default())
        self.tree = app_commands.CommandTree(self)

    async def setup_hook(self):
        # Synchronizacja komend slash 
        await self.tree.sync()
        print("Komendy Slash zsynchronizowane.")

bot = MyBot()

def get_jenkins_auth():
    return BasicAuth(JENKINS_USER, JENKINS_TOKEN)

class ApprovalView(View):
    def __init__(self, job_name, build_number):
        super().__init__(timeout=None) 
        self.job_name = job_name
        self.build_number = build_number

    @discord.ui.button(label="Zatwierdź wdrożenie", style=discord.ButtonStyle.success, custom_id="approve_btn")
    async def approve(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        url = f"{JENKINS_URL}/job/{self.job_name}/{self.build_number}/input/Approval/proceed"
        
        payload = {'json': '{}'}
        
        async with aiohttp.ClientSession() as session:
            async with session.post(url, auth=get_jenkins_auth(), data=payload) as response:
                if response.status in [200, 302]:
                    # Naprawiona, połączona linia wysyłania wiadomości:
                    await interaction.followup.send(f"Wdrożenie #{self.build_number} zostało **zaakceptowane** przez {interaction.user.mention}! Pipeline rusza dalej.")
                    self.stop()
                else:
                    await interaction.followup.send(f"Nie udało się zatwierdzić buildu w Jenkinsie. Kod błędu: {response.status}")

    @discord.ui.button(label="Odrzuć", style=discord.ButtonStyle.danger, custom_id="reject_btn")
    async def reject(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        url = f"{JENKINS_URL}/job/{self.job_name}/{self.build_number}/input/Approval/abort"
        
        payload = {'json': '{}'}
        
        async with aiohttp.ClientSession() as session:
            async with session.post(url, auth=get_jenkins_auth(), data=payload) as response:
                if response.status in [200, 302]:
                    await interaction.followup.send(f"Wdrożenie #{self.build_number} zostało **odrzucone** przez {interaction.user.mention}. Pipeline przerwany.")
                    self.stop()
                else:
                    await interaction.followup.send(f"Nie udało się przerwać buildu w Jenkinsie. Kod błędu: {response.status}")

@bot.tree.command(name="status", description="Sprawdza status ostatniego wykonania potoku")
async def status(interaction: discord.Interaction):
    await interaction.response.defer()
    url = f"{JENKINS_URL}/job/{JOB_NAME}/lastBuild/api/json"
    
    async with aiohttp.ClientSession() as session:
        try:
            async with session.get(url, auth=get_jenkins_auth()) as response:
                if response.status == 200:
                    data = await response.json()
                    build_num = data.get("number")
                    is_building = data.get("building", False)
                    raw_result = data.get("result")
                    
                    if is_building:
                        result_text = "W trakcie budowania"
                        color = discord.Color.orange()
                    else:
                        result_text = "SUCCESS" if raw_result == "SUCCESS" else f"{raw_result}"
                        color = discord.Color.green() if raw_result == "SUCCESS" else discord.Color.red()

                    embed = discord.Embed(title=f"Status projektu: {JOB_NAME}", color=color)
                    embed.add_field(name="Numer buildu", value=f"#{build_num}", inline=True)
                    embed.add_field(name="Wynik", value=result_text, inline=True)
                    embed.add_field(name="Szczegóły", value=data.get("url"), inline=False)
                    await interaction.followup.send(embed=embed)
                else:
                    await interaction.followup.send(f"Błąd podczas odpytywania Jenkinsa. Status: {response.status}")
        except Exception as e:
            await interaction.followup.send(f"Nie można połączyć się z Jenkinsem: {str(e)}")


@bot.tree.command(name="build", description="Uruchamia potok dla określonej gałęzi")
@app_commands.describe(branch="Nazwa gałęzi z repozytorium GitHub")
async def build(interaction: discord.Interaction, branch: str):
    await interaction.response.defer()
    url = f"{JENKINS_URL}/job/{JOB_NAME}/buildWithParameters"
    params = {"BRANCH": branch}
    
    async with aiohttp.ClientSession() as session:
        try:
            async with session.post(url, auth=get_jenkins_auth(), params=params) as response:
                if response.status in [200, 201, 202, 302]:
                    await interaction.followup.send(f"Pomyślnie wyzwolono build w Jenkinsie dla gałęzi `origin/{branch}`!")
                else:
                    await interaction.followup.send(f"Jenkins odrzucił żądanie budowania. Status: {response.status}")
        except Exception as e:
            await interaction.followup.send(f"Awaria połączenia z serwerem CI/CD: {str(e)}")



@bot.tree.command(name="rollback", description="Uruchamia procedurę przywrócenia wskazanej wersji")
@app_commands.describe(version="Numer buildu lub tag obrazu Docker do przywrócenia")
async def rollback(interaction: discord.Interaction, version: str):
    await interaction.response.defer()
    url = f"{JENKINS_URL}/job/{JOB_NAME}/buildWithParameters"
    params = {"ROLLBACK_VERSION": version, "BRANCH": "master"}
    
    async with aiohttp.ClientSession() as session:
        try:
            async with session.post(url, auth=get_jenkins_auth(), params=params) as response:
                if response.status in [200, 201, 202, 302]:
                    await interaction.followup.send(f"**URUCHOMIONO ROLLBACK!** Jenkins wdraża wersję/tag: `{version}` na środowisko produkcyjne.")
                else:
                    await interaction.followup.send(f"Nie udało się wyzwolić procedury rollback. Status: {response.status}")
        except Exception as e:
            await interaction.followup.send(f"Błąd komunikacji z bazą CI/CD: {str(e)}")



async def handle_jenkins_request(request):
    try:
        data = await request.json()
        job_name = data.get("job")
        build_num = data.get("build")

        channel = bot.get_channel(CHANNEL_ID)
        if channel:
            view = ApprovalView(job_name, build_num)
            await channel.send(
                f"**Potok {job_name} #{build_num} oczekuje na weryfikację!** \nCzy zgadzasz się na wdrożenie zmian na produkcję?", 
                view=view
            )
            return web.Response(text="Wiadomość wysłana na Discord", status=200)
        return web.Response(text="Nie znaleziono kanału", status=404)
    except Exception as e:
        return web.Response(text=str(e), status=500)

async def start_server():
    app = web.Application()
    app.router.add_post('/request-approval', handle_jenkins_request)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', 5000)
    await site.start()
    print("Wewnętrzny serwer HTTP bota słucha na porcie 5000.")


async def main():
    asyncio.create_task(start_server())
    await bot.start(TOKEN)

if __name__ == "__main__":
    asyncio.run(main())