from arkady_plugin import Plugin, ArkadyPluginEnv

plugin = Plugin(ArkadyPluginEnv(MAX_REQUEST_TIMEOUT=120))

if __name__ == '__main__':
    plugin.run()
