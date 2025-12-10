"""
gtk_utils.py – GTK-specific utility functions.

This module contains functions that depend on GTK/GDK, separated from utils.py
to allow the core utilities to be toolkit-agnostic.
"""

import re
import gi
gi.require_version('Gtk', '3.0')
from gi.repository import Gtk, GdkPixbuf, Gdk


def parse_color_to_rgba(color_str):
    """Convert a color string (rgb or hex) to Gdk.RGBA object.
    
    Args:
        color_str (str): Color in 'rgb(r,g,b)' or hex format
    
    Returns:
        Gdk.RGBA: Color object for GTK widgets
    """
    rgba = Gdk.RGBA()
    if color_str.startswith('rgb('):
        # Extract RGB values from the rgb() format
        rgb_match = re.match(r'rgb\((\d+),(\d+),(\d+)\)', color_str)
        if rgb_match:
            r = int(rgb_match.group(1)) / 255.0
            g = int(rgb_match.group(2)) / 255.0
            b = int(rgb_match.group(3)) / 255.0
            rgba.red = r
            rgba.green = g
            rgba.blue = b
            rgba.alpha = 1.0
    else:
        rgba.parse(color_str)
    return rgba


def insert_resized_image(buffer, iter, img_path, text_view=None, window=None):
    """Insert an image into the text buffer with responsive sizing.

    The image will shrink to fit the available width in the TextView while
    preserving aspect ratio, but it will never be upscaled beyond its
    original resolution.
    """

    try:
        # Create a scrolled window to contain the image
        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.EXTERNAL, Gtk.PolicyType.NEVER)
        scroll.set_hexpand(True)
        scroll.set_vexpand(False)  # Don't expand vertically
        scroll.set_size_request(100, -1)  # Set minimum width

        # Load the original image
        pixbuf = GdkPixbuf.Pixbuf.new_from_file(img_path)
        original_width = pixbuf.get_width()
        original_height = pixbuf.get_height()

        # Create the image widget
        image = Gtk.Image.new_from_pixbuf(pixbuf)
        image.set_size_request(100, -1)  # Set minimum width for image too
        image.set_vexpand(False)  # Don't expand vertically
        
        # Add right-click context menu to save image
        # Wrap image in EventBox to receive button events
        if window is not None:
            event_box = Gtk.EventBox()
            event_box.add(image)
            event_box.set_events(Gdk.EventMask.BUTTON_PRESS_MASK)
            
            def on_image_button_press(widget, event):
                if event.button == 3:  # Right click
                    menu = Gtk.Menu()
                    save_item = Gtk.MenuItem(label="Save Image As...")
                    save_item.connect("activate", lambda w: window.save_image_to_file(img_path))
                    menu.append(save_item)
                    menu.show_all()
                    menu.popup_at_pointer(event)
                    return True
                return False
            
            event_box.connect("button-press-event", on_image_button_press)
            image_widget = event_box
        else:
            image_widget = image

        def on_size_allocate(widget, allocation):
            if text_view is None:
                return

            # Available width inside the TextView
            allocated_width = text_view.get_allocated_width()
            if allocated_width <= 0:
                return

            # Target width: fit within TextView, but never exceed original width
            target_width = max(min(allocated_width - 20, original_width), 100)

            # If the target width is effectively the same as the original, keep original pixbuf
            if target_width == original_width:
                scaled = pixbuf
            else:
                # Calculate new height maintaining aspect ratio
                target_height = int(target_width * (original_height / original_width))
                scaled = pixbuf.scale_simple(
                    target_width,
                    target_height,
                    GdkPixbuf.InterpType.BILINEAR
                )

            image.set_from_pixbuf(scaled)

            # Force the scroll window to request the new size
            scroll.set_size_request(target_width, -1)

        if text_view is not None:
            text_view.connect('size-allocate', on_size_allocate)

        # Add image (or event box) to scrolled window
        scroll.add(image_widget)

        # Insert into buffer
        anchor = buffer.create_child_anchor(iter)
        if text_view is not None:
            text_view.add_child_at_anchor(scroll, anchor)
        scroll.show_all()

    except Exception as e:
        print(f"Error processing image: {e}")
        import traceback
        traceback.print_exc()
