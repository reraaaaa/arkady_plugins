from arkady_plugin import Plugin, ArkadyPluginEnv
import logging

logging.basicConfig(level=logging.INFO)

plugin = Plugin(ArkadyPluginEnv())

if __name__ == '__main__':
    plugin.run()
