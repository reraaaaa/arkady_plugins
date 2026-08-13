from arkady_plugin import ArkadyPluginEnv, Plugin

plugin = Plugin(ArkadyPluginEnv(MAX_REQUEST_TIMEOUT=120))

if __name__ == '__main__':
    plugin.run()
