#!/bin/bash

# Set XDG defaults if not already set
XDG_CONFIG_HOME="${XDG_CONFIG_HOME:-$HOME/.config}"
XDG_DATA_HOME="${XDG_DATA_HOME:-$HOME/.local/share}"

# Check if OPENAI_API_KEY is set
if [ -z "$OPENAI_API_KEY" ]; then
    echo "OpenAI API key not found."
    echo "Please enter your OpenAI API key (starts with 'sk-'):"
    read -r api_key
else
    api_key="$OPENAI_API_KEY"
fi

if [ -z "$GEMINI_API_KEY" ]; then
    echo "Optional: enter your Gemini API key (starts with 'AI'):"
    read -r gemini_key
else
    gemini_key="$GEMINI_API_KEY"
fi

echo "Setting up ChatGTK desktop integration..."
# Get the absolute path to the current directory
INSTALL_DIR=$(pwd)

# Create a wrapper script that sets up the environment
echo "Creating launcher script..."
cat << EOF > chatgtk-launcher.sh
#!/bin/bash
export OPENAI_API_KEY="${api_key}"
export GEMINI_API_KEY="${gemini_key}"
cd "${INSTALL_DIR}"
exec python3 src/ChatGTK.py
EOF

# Make wrapper executable
chmod +x chatgtk-launcher.sh

echo "Creating desktop entry..."
# Create desktop entry using the wrapper script
cat << EOF > chatgtk.desktop
[Desktop Entry]
Version=1.0
Type=Application
Name=ChatGTK
Comment=OpenAI Chat Client with GTK interface
Exec=${INSTALL_DIR}/chatgtk-launcher.sh
Icon=${INSTALL_DIR}/src/icon.png
Categories=Network;Chat;AI;
Terminal=false
StartupNotify=true
Keywords=chat;ai;gpt;openai;
EOF

echo "Making desktop entry executable..."
# Make it executable
chmod +x chatgtk.desktop

echo "Installing desktop entry..."
# Copy to local applications directory
mkdir -p "${XDG_DATA_HOME}/applications/"
mv chatgtk.desktop "${XDG_DATA_HOME}/applications/"

echo "Updating desktop database..."
# Update desktop database
update-desktop-database "${XDG_DATA_HOME}/applications/"

echo "Installation complete! You can now find ChatGTK in your applications menu."